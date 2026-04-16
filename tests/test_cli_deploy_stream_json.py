"""Regression tests for `agentlab deploy --output-format stream-json` (R4.6).

The Click wrapper delegates the stream-json rendering path to
``run_deploy_in_process``, which fires the same event-name sequence the
subprocess path previously emitted. This test captures that sequence and
asserts it ends with a ``deploy_complete`` terminal envelope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _parse_events(output: str) -> list[dict]:
    return [
        json.loads(line)
        for line in output.splitlines()
        if line.strip().startswith("{")
    ]


def _seed_config(workspace: Path, version: int = 1) -> None:
    import yaml
    agentlab_dir = workspace / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = workspace / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    (configs_dir / f"v{version:03d}.yaml").write_text(
        yaml.safe_dump({"name": "test", "system_prompt": "hi", "model": "stub"})
    )
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


def test_cli_deploy_stream_json_event_sequence_unchanged(runner: CliRunner) -> None:
    """``agentlab deploy --dry-run --output-format stream-json`` event sequence.

    The invariant the slash handler + loader consumers rely on: the stream
    begins with ``phase_started`` and ends with ``deploy_complete``. Timestamps
    are stripped before comparison because they are wall-clock dependent.
    """
    from runner import cli

    with runner.isolated_filesystem() as fs:
        _seed_config(Path(fs))
        result = runner.invoke(
            cli,
            ["deploy", "--dry-run", "--output-format", "stream-json"],
        )

    assert result.exit_code == 0, result.output
    payloads = _parse_events(result.output)
    for p in payloads:
        p.pop("timestamp", None)

    names = [p["event"] for p in payloads]
    assert names[0] == "phase_started"
    assert names[-1] == "deploy_complete"

    final = payloads[-1]
    for key in ("attempt_id", "deployment_id", "status", "verdict"):
        assert key in final, f"expected {key!r} in terminal event: {final!r}"
