"""Smoke test for transcript ingestion and agent generation from the CLI."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from runner import cli


def test_transcript_cli_upload_report_and_generate_agent() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        transcript_file = Path("transcripts.json")
        transcript_file.write_text(
            json.dumps(
                [
                    {
                        "conversation_id": "hist-001",
                        "session_id": "sess-001",
                        "user_message": "Where is my order?",
                        "agent_response": "I need the order number before I can look it up.",
                        "outcome": "transfer",
                    }
                ]
            ),
            encoding="utf-8",
        )

        upload_result = runner.invoke(cli, ["import", "transcript", "upload", str(transcript_file)])
        assert upload_result.exit_code == 0, upload_result.output

        report_id = upload_result.output.strip().split()[-1]

        report_result = runner.invoke(cli, ["import", "transcript", "report", report_id])
        assert report_result.exit_code == 0, report_result.output
        assert "conversation_count" in report_result.output

        generate_result = runner.invoke(
            cli,
            [
                "import",
                "transcript",
                "generate-agent",
                report_id,
                "--prompt",
                "Build a support agent that closes order tracking gaps",
                "--output",
                "generated-agent.yaml",
            ],
        )
        assert generate_result.exit_code == 0, generate_result.output
        assert Path("generated-agent.yaml").exists()

