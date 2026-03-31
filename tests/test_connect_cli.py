"""Tests for the new `autoagent connect` CLI flow."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from runner import cli


def test_connect_transcript_creates_workspace_with_imported_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Connecting a transcript file should scaffold a real import workspace."""

    transcript_file = tmp_path / "conversations.jsonl"
    transcript_file.write_text(
        json.dumps(
            {
                "id": "conv-1",
                "messages": [
                    {"role": "user", "content": "Reset my password."},
                    {"role": "assistant", "content": "Use the reset link in your email."},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "connect",
            "transcript",
            "--file",
            str(transcript_file),
            "--name",
            "connected-transcript",
        ],
    )

    workspace = tmp_path / "connected-transcript"

    assert result.exit_code == 0, result.output
    assert workspace.is_dir()
    assert (workspace / ".autoagent" / "adapter_spec.json").exists()
    assert (workspace / ".autoagent" / "adapter_config.json").exists()
    assert (workspace / "configs" / "v001.yaml").exists()
    assert (workspace / "evals" / "cases" / "imported_connect.yaml").exists()
    adapter_spec = json.loads((workspace / ".autoagent" / "adapter_spec.json").read_text(encoding="utf-8"))
    assert adapter_spec["adapter"] == "transcript"
    assert adapter_spec["agent_name"] == "transcript-import"
