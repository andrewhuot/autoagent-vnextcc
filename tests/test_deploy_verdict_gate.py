"""Tests for R1.9: deploy verdict gate that blocks on degraded eval."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_deploy(
    *args: str,
    cwd: Path | None = None,
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    # Ensure the runner module can be imported from the repo even when cwd is a tmp dir.
    existing_pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing_pypath}" if existing_pypath else str(REPO_ROOT)
    )
    return subprocess.run(
        [sys.executable, "-m", "runner", "deploy", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or REPO_ROOT),
    )


def _seed_eval(workspace: Path, composite: float) -> None:
    """Write a fake latest eval payload with the given composite score.

    `_latest_eval_result_file()` globs for ``eval_results*.json`` or
    ``*results*.json`` under cwd and ``.agentlab/``, picking the newest by mtime.
    """
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


def _seed_config(workspace: Path) -> None:
    configs = workspace / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    (configs / "v001.json").write_text(
        json.dumps(
            {
                "name": "test",
                "system_prompt": "hi",
                "model": "stub",
            }
        )
    )


def test_degraded_eval_blocks_deploy(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.65)  # "Degraded"
    result = _run_deploy("--dry-run", cwd=tmp_path)
    assert result.returncode == 13, (result.stdout, result.stderr)
    combined = result.stdout + result.stderr
    assert "egraded" in combined.lower() or "eeds attention" in combined.lower()


def test_needs_attention_eval_blocks_deploy(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.4)  # "Needs Attention"
    result = _run_deploy("--dry-run", cwd=tmp_path)
    assert result.returncode == 13, (result.stdout, result.stderr)


def test_nominal_eval_allows_deploy(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.85)  # "Nominal"
    result = _run_deploy("--dry-run", cwd=tmp_path)
    # Should not exit 13; any other exit code (0 or command-specific) is fine.
    assert result.returncode != 13, (result.stdout, result.stderr)


def test_healthy_eval_allows_deploy(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.95)  # "Healthy"
    result = _run_deploy("--dry-run", cwd=tmp_path)
    assert result.returncode != 13


def test_missing_eval_allows_deploy(tmp_path):
    """No eval = no verdict to gate on. Deploy proceeds (user's problem to notice)."""
    _seed_config(tmp_path)
    result = _run_deploy("--dry-run", cwd=tmp_path)
    assert result.returncode != 13


def test_force_deploy_without_reason_fails(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.65)
    result = _run_deploy("--force-deploy-degraded", "--dry-run", cwd=tmp_path)
    combined = result.stdout + result.stderr
    assert result.returncode != 0  # Should fail
    assert "--reason" in combined or "reason" in combined.lower()


def test_force_deploy_with_short_reason_fails(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.65)
    result = _run_deploy(
        "--force-deploy-degraded", "--reason", "short", "--dry-run", cwd=tmp_path
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert (
        "10 char" in combined.lower()
        or "too short" in combined.lower()
        or "minimum" in combined.lower()
    )


def test_force_deploy_with_valid_reason_proceeds(tmp_path):
    _seed_config(tmp_path)
    _seed_eval(tmp_path, composite=0.65)
    result = _run_deploy(
        "--force-deploy-degraded",
        "--reason",
        "Rolling back a worse regression in prod",
        "--dry-run",
        cwd=tmp_path,
    )
    assert result.returncode != 13, (result.stdout, result.stderr)
    # Warning should be visible
    combined = result.stdout + result.stderr
    assert (
        "override" in combined.lower()
        or "force" in combined.lower()
        or "degraded" in combined.lower()
    )


def test_gate_respects_score_field_nested_shape(tmp_path):
    """Some eval payloads wrap composite under 'score'. Gate must handle both shapes."""
    _seed_config(tmp_path)
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    nested = {"score": {"composite": 0.4}, "results": []}
    (agentlab_dir / "eval_results_nested.json").write_text(json.dumps(nested))
    result = _run_deploy("--dry-run", cwd=tmp_path)
    assert result.returncode == 13, (result.stdout, result.stderr)
