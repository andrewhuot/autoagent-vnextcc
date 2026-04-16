"""Tests for cli.commands.deploy.run_deploy_in_process (R4.6).

Exercises the extracted pure business-logic function shared by the Click
wrapper (``agentlab deploy``) and the ``/deploy`` slash handler. The
subprocess path is replaced by an in-process call that fires an
``on_event`` callback for every stream-json event the deploy run would
normally emit.

Slice A invariant: the R1.9 verdict gate (degraded/needs-attention eval
composite blocks deploy) must still work — ``run_deploy_in_process``
raises :class:`DeployVerdictBlockedError` rather than calling
``sys.exit``, and emits a terminal ``deploy_complete`` event with
``status="blocked"`` BEFORE raising so event consumers see a well-formed
envelope either way.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _seed_config(workspace: Path, version: int = 1) -> None:
    """Write a minimal config manifest that makes deploy discover a candidate."""
    agentlab_dir = workspace / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = workspace / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    # Create a config YAML that matches deployer expectations.
    import yaml
    (configs_dir / f"v{version:03d}.yaml").write_text(
        yaml.safe_dump({"name": "test", "system_prompt": "hi", "model": "stub"})
    )
    # Seed the version manifest so deployer finds it.
    manifest_path = configs_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "active_version": None,
                "canary_version": None,
                "versions": [
                    {
                        "version": version,
                        "config_hash": "abcdef012345",
                        "filename": f"v{version:03d}.yaml",
                        "timestamp": 1700000000.0,
                        "scores": {"composite": 0.9},
                        "status": "candidate",
                    }
                ],
            }
        )
    )


def _seed_eval(workspace: Path, composite: float) -> None:
    """Write a fake latest eval payload with the given composite score."""
    agentlab_dir = workspace / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "composite": composite,
        "quality": composite,
        "safety": 1.0 if composite >= 0.5 else 0.0,
        "latency": 0.9,
        "cost": 0.9,
        "results": [],
    }
    (agentlab_dir / "eval_results_latest.json").write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# 1 — event shape
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_emits_expected_events(cli_runner: CliRunner) -> None:
    """Dry-run deploy must emit phase_started + phase_completed + deploy_complete."""
    from cli.commands.deploy import run_deploy_in_process

    events: list[dict[str, Any]] = []
    with cli_runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        run_deploy_in_process(
            dry_run=True,
            on_event=events.append,
        )

    names = [e.get("event") for e in events]
    assert "phase_started" in names
    assert "phase_completed" in names
    assert "deploy_complete" in names


# ---------------------------------------------------------------------------
# 2 — terminal event shape
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_emits_deploy_complete_terminal_event(
    cli_runner: CliRunner,
) -> None:
    """The last event is ``deploy_complete`` carrying attempt/deployment metadata."""
    from cli.commands.deploy import run_deploy_in_process

    events: list[dict[str, Any]] = []
    with cli_runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        run_deploy_in_process(
            dry_run=True,
            on_event=events.append,
        )

    assert events, "expected at least one event"
    final = events[-1]
    assert final.get("event") == "deploy_complete"
    # Required keys must exist (values may be None on some paths).
    for key in ("attempt_id", "deployment_id", "status", "verdict"):
        assert key in final, f"expected {key!r} in terminal event: {final!r}"
    assert final["status"] in {"ok", "failed", "blocked", "cancelled"}


# ---------------------------------------------------------------------------
# 3 — result dataclass
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_returns_result_dataclass(cli_runner: CliRunner) -> None:
    from cli.commands.deploy import DeployRunResult, run_deploy_in_process

    with cli_runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        result = run_deploy_in_process(
            dry_run=True,
            on_event=lambda _: None,
        )

    assert isinstance(result, DeployRunResult)
    assert result.status in {"ok", "failed", "blocked", "cancelled"}


# ---------------------------------------------------------------------------
# 4 — R1 verdict gate preservation
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_raises_verdict_blocked_error_when_blocked(
    cli_runner: CliRunner,
) -> None:
    """Blocked verdict → DeployVerdictBlockedError.

    CRITICAL: the terminal ``deploy_complete`` event must be emitted with
    ``status="blocked"`` BEFORE the exception is raised so consumers always
    see a well-formed envelope.
    """
    from cli.commands.deploy import (
        DeployVerdictBlockedError,
        run_deploy_in_process,
    )

    events: list[dict[str, Any]] = []
    with cli_runner.isolated_filesystem() as fs:
        ws = Path(fs)
        _seed_config(ws)
        _seed_eval(ws, composite=0.4)  # "Needs Attention" — blocked
        with pytest.raises(DeployVerdictBlockedError):
            run_deploy_in_process(
                dry_run=True,
                on_event=events.append,
            )

    assert events, "expected a terminal event even when verdict-blocked"
    final = events[-1]
    assert final.get("event") == "deploy_complete"
    assert final.get("status") == "blocked"
    assert final.get("verdict") == "blocked"


# ---------------------------------------------------------------------------
# 5 — strict-live fallback
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_raises_mock_fallback_error_on_strict_live(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """strict-live with a mock-fallback warning must raise MockFallbackError."""
    from cli.commands.deploy import run_deploy_in_process
    from cli.strict_live import MockFallbackError

    # Force-record a mock warning by monkeypatching the deploy gate to
    # raise the error directly (the simplest path). R4.6 is about the
    # plumbing — the strict-live check is applied by deploy itself via
    # StrictLivePolicy.
    import cli.commands.deploy as deploy_mod

    def _raise_mock(**_kwargs: Any) -> None:
        raise MockFallbackError(["mock-fallback-in-test"])

    monkeypatch.setattr(deploy_mod, "_strict_live_gate", _raise_mock, raising=False)

    with cli_runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        with pytest.raises(MockFallbackError):
            run_deploy_in_process(
                dry_run=True,
                strict_live=True,
                on_event=lambda _: None,
            )


# ---------------------------------------------------------------------------
# 6 — subprocess-free
# ---------------------------------------------------------------------------


def test_run_deploy_in_process_never_calls_subprocess_popen(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-process path must NOT spawn any subprocess."""
    from cli.commands.deploy import run_deploy_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    with cli_runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        run_deploy_in_process(
            dry_run=True,
            on_event=lambda _: None,
        )

    sentinel.assert_not_called()
