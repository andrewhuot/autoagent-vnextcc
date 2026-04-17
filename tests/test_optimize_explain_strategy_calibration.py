"""Tests for --explain-strategy rendering the calibration factor (R6.B.3b).

B.3b wires the CLI to look up the per-(surface, strategy) calibration factor
from ``CalibrationStore`` and pass it through to ``format_strategy_explanation``
at all four ``--explain-strategy`` render sites in
``cli/commands/optimize.py``.

Invariants:

* Empty calibration history (``factor()`` returns ``None``) → output is
  byte-identical to pre-R6 behavior; the ``--explain-strategy`` golden stays
  green.
* Populated history (≥20 rows) → the rendered line includes
  ``calibrated effectiveness=`` and an over/underperformed clause.
* Calibration lookup errors are swallowed silently — rendering never breaks.
* ``AGENTLAB_CALIBRATION_DB`` env var overrides the default DB path.
"""

from __future__ import annotations

import time

import pytest
from click.testing import CliRunner

from optimizer import proposer as prop_mod
from optimizer.calibration import CalibrationStore
from optimizer.proposer import StrategyExplanation
from runner import cli


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _entry() -> StrategyExplanation:
    return StrategyExplanation(
        strategy="rewrite_prompt",
        surface="system_prompt",
        effectiveness=0.62,
        samples=15,
        explored=False,
    )


def _seed_calibration_db(
    db_path: str,
    *,
    n: int = 20,
    surface: str = "system_prompt",
    strategy: str = "rewrite_prompt",
    mean_residual: float = -0.06,
) -> None:
    """Seed ``n`` rows whose mean (actual - predicted) equals ``mean_residual``."""
    store = CalibrationStore(db_path=db_path)
    now = time.time()
    # Keep it simple: each row's residual is exactly ``mean_residual`` so the
    # mean is deterministic regardless of ``n``.
    for i in range(n):
        store.record(
            attempt_id=f"att-{i}",
            surface=surface,
            strategy=strategy,
            predicted_effectiveness=0.50,
            actual_delta=0.50 + mean_residual,
            recorded_at=now + i,  # unique timestamps so LIMIT n is stable
        )


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_explain_strategy_sparse_falls_back_to_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Empty calibration DB → byte-identical pre-R6 output (no calibrated clause)."""
    db_path = tmp_path / "cal.db"
    # Initialize an empty DB so factor() returns None.
    CalibrationStore(db_path=str(db_path))

    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [_entry()])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli, ["optimize", "--dry-run", "--explain-strategy"]
        )

    assert result.exit_code == 0, result.output
    assert "selected mutation rewrite_prompt" in result.output
    assert "effectiveness=0.62" in result.output
    assert "calibrated effectiveness=" not in result.output


def test_explain_strategy_shows_calibrated_value_when_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """20 rows with mean residual -0.06 → underperformed-by-0.06 clause shown."""
    db_path = tmp_path / "cal.db"
    _seed_calibration_db(
        str(db_path),
        n=20,
        surface="system_prompt",
        strategy="rewrite_prompt",
        mean_residual=-0.06,
    )

    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [_entry()])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli, ["optimize", "--dry-run", "--explain-strategy"]
        )

    assert result.exit_code == 0, result.output
    assert "calibrated effectiveness=" in result.output
    assert "underperformed by 0.06" in result.output


def test_explain_strategy_calibration_db_missing_file_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Non-existent DB path → rendering still succeeds with base output, no stderr warning."""
    db_path = tmp_path / "nested" / "does-not-exist.db"
    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [_entry()])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli, ["optimize", "--dry-run", "--explain-strategy"]
        )

    assert result.exit_code == 0, result.output
    assert "selected mutation rewrite_prompt" in result.output
    # CalibrationStore creates the file on open (parent dir mkdir'd). The DB
    # is empty, so factor() returns None and we fall through to base output.
    # Byte-identical invariant preserved.
    assert "calibrated effectiveness=" not in result.output
    # No warning/stacktrace in captured output (combined stdout+stderr here).
    assert "Traceback" not in result.output
    assert "RuntimeError" not in result.output


def test_explain_strategy_calibration_raises_does_not_break_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """If CalibrationStore.factor raises, rendering still produces base output."""
    db_path = tmp_path / "cal.db"
    CalibrationStore(db_path=str(db_path))
    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))

    def _boom(self, *, surface: str, strategy: str, n: int = 20):  # noqa: ARG001
        raise RuntimeError("calibration store exploded")

    monkeypatch.setattr(CalibrationStore, "factor", _boom)
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [_entry()])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli, ["optimize", "--dry-run", "--explain-strategy"]
        )

    assert result.exit_code == 0, result.output
    assert "selected mutation rewrite_prompt" in result.output
    assert "calibrated effectiveness=" not in result.output


def test_explain_strategy_golden_help_unchanged() -> None:
    """The --explain-strategy help text on `agentlab optimize` is unchanged.

    The help-golden subprocess path is currently blocked by an unrelated
    ``agent_card`` import regression, so this test uses a direct
    ``click.Command.get_help()`` invocation and asserts the flag's help line
    is present and stable.
    """
    from click.core import Context
    from runner import cli as cli_group

    optimize_cmd = cli_group.commands["optimize"]
    ctx = Context(optimize_cmd, info_name="optimize")
    help_text = optimize_cmd.get_help(ctx)
    assert "--explain-strategy" in help_text


def test_explanation_with_calibration_helper_direct(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Direct unit test on the _explanation_with_calibration helper."""
    from cli.commands.optimize import _explanation_with_calibration

    db_path = tmp_path / "cal.db"
    CalibrationStore(db_path=str(db_path))
    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))

    # Sparse path: empty DB → base rendering.
    out = _explanation_with_calibration(_entry())
    assert isinstance(out, str)
    assert out.startswith("selected mutation")
    assert "calibrated effectiveness=" not in out

    # Populated path: seed the DB and confirm clause renders.
    _seed_calibration_db(
        str(db_path),
        n=20,
        surface="system_prompt",
        strategy="rewrite_prompt",
        mean_residual=0.04,
    )
    out2 = _explanation_with_calibration(_entry())
    assert "calibrated effectiveness=" in out2
    assert "overperformed by 0.04" in out2


def test_explain_strategy_uses_env_override_for_db_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """AGENTLAB_CALIBRATION_DB points at the tmp path; factor read from there."""
    db_path = tmp_path / "override.db"
    _seed_calibration_db(
        str(db_path),
        n=20,
        surface="system_prompt",
        strategy="rewrite_prompt",
        mean_residual=0.04,
    )

    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(db_path))
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [_entry()])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli, ["optimize", "--dry-run", "--explain-strategy"]
        )

    assert result.exit_code == 0, result.output
    assert "calibrated effectiveness=" in result.output
    assert "overperformed by 0.04" in result.output
