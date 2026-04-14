"""Regression coverage for the structured Workbench terminal surfaces."""

from __future__ import annotations

import click

from cli.workbench_render import render_candidate_summary


def test_candidate_summary_uses_structured_panes(capsys) -> None:
    render_candidate_summary(
        {
            "project_id": "wb-123",
            "name": "Refund Agent",
            "target": "portable",
            "environment": "draft",
            "version": 2,
            "run": {
                "status": "completed",
                "execution_mode": "mock",
                "provider": "local",
                "model": "test-model",
            },
            "summary": {"validation_status": "passed"},
            "agent_card": {
                "name": "Refund Agent",
                "model": "gpt-test",
                "counts": {"tools": 3, "guardrails": 2, "eval_suites": 1},
            },
            "artifact_count": 4,
            "turn_count": 6,
            "bridge": {
                "evaluation": {
                    "label": "Save candidate before Eval",
                    "description": "Materialize a config first.",
                    "readiness_state": "needs_materialization",
                    "blocking_reasons": ["candidate has not been saved"],
                },
                "optimization": {
                    "label": "Eval candidate not ready",
                    "description": "Run Eval after saving.",
                },
            },
            "next_commands": {
                "save": "agentlab workbench save --project-id wb-123",
                "eval": "agentlab eval run --config configs/v002.yaml",
                "iterate": "agentlab workbench iterate --project-id wb-123",
            },
        }
    )

    plain = click.unstyle(capsys.readouterr().out)
    assert " Workbench Candidate " in plain
    assert " Readiness " in plain
    assert " Provenance " in plain
    assert "Save candidate before Eval" in plain
    assert "candidate has not been saved" in plain
    assert "agentlab workbench save --project-id wb-123" in plain
