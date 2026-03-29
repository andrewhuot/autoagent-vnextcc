"""Smoke test for persisted autofix application output."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from optimizer.autofix import AutoFixProposal, AutoFixStore
from runner import cli


def test_autofix_apply_persists_output() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        Path(".autoagent").mkdir(parents=True, exist_ok=True)
        store = AutoFixStore()
        proposal = AutoFixProposal(
            proposal_id="persist001",
            mutation_name="instruction_rewrite",
            surface="prompts.root",
            params={"target": "root", "text": "Prioritize refunds and verify eligibility before escalation."},
            expected_lift=0.08,
            diff_preview="Rewrite refund handling guidance",
        )
        store.save(proposal)

        apply_result = runner.invoke(cli, ["autofix", "apply", proposal.proposal_id])
        assert apply_result.exit_code == 0, apply_result.output

        refreshed = AutoFixStore().get(proposal.proposal_id)
        assert refreshed is not None
        assert refreshed.status == "applied"
        assert len(list(Path("configs").glob("v*.yaml"))) >= 2

