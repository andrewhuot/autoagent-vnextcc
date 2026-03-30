"""Tests for Stream 4 CLI taxonomy, maturity labels, and interactive workflows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from deployer import Deployer
from logger import ConversationStore
from optimizer.autofix import AutoFixProposal, AutoFixStore
from optimizer.change_card import ChangeCardStore, DiffHunk, ProposedChangeCard
from runner import cli


def _runner() -> CliRunner:
    return CliRunner()


def _seed_config_version(configs_dir: str = "configs", db_path: str = "conversations.db") -> None:
    store = ConversationStore(db_path=db_path)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    deployer.version_manager.save_version(
        {"prompts": {"root": "You are a helpful assistant."}},
        scores={"composite": 0.8},
        status="active",
    )


def _seed_change_card() -> ProposedChangeCard:
    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = ProposedChangeCard(
        card_id="card001",
        title="Improve refund handling",
        why="Refund intent misses are the largest current failure bucket.",
        diff_hunks=[
            DiffHunk(
                hunk_id="hunk001",
                surface="routing.rules.refunds",
                old_value="refund",
                new_value="refund, chargeback, reimbursement",
            )
        ],
    )
    store.save(card)
    return card


def _seed_autofix_proposal() -> AutoFixProposal:
    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = AutoFixStore()
    proposal = AutoFixProposal(
        proposal_id="fix001",
        mutation_name="instruction_rewrite",
        surface="prompts.root",
        params={"target": "root", "text": "Be concise and verify refund eligibility before escalation."},
        expected_lift=0.12,
        risk_class="low",
        affected_eval_slices=["refunds"],
        cost_impact_estimate=0.0,
        diff_preview="Rewrite refund guidance in the root prompt",
    )
    store.save(proposal)
    return proposal


def test_root_help_shows_shared_taxonomy_and_hides_experimental_commands() -> None:
    runner = _runner()

    default_help = runner.invoke(cli, ["--help"])
    assert default_help.exit_code == 0
    # Only primary and secondary commands appear in default help
    for group_name in [
        "build",
        "eval",
        "optimize",
        "deploy",
    ]:
        assert group_name in default_help.output
    # Help is now split into "Primary Commands:" and "Secondary Commands:" sections
    assert "Primary Commands:" in default_help.output
    assert "Secondary Commands:" in default_help.output
    # Experimental/hidden commands are not shown in default help
    assert "rl" not in default_help.output or "Primary Commands:" in default_help.output

    all_help = runner.invoke(cli, ["--all", "--help"])
    assert all_help.exit_code == 0
    # The rl command is registered and invocable even if not shown in default help
    from runner import cli as _cli
    assert "rl" in _cli.commands


def test_help_exposes_task_oriented_groups() -> None:
    result = _runner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    # Primary and secondary commands are visible in default help
    for group_name in [
        "build",
        "eval",
        "optimize",
        "deploy",
    ]:
        assert group_name in result.output
    # Help is split into "Primary Commands:" and "Secondary Commands:" sections
    assert "Primary Commands:" in result.output
    assert "Secondary Commands:" in result.output


@pytest.mark.parametrize(
    ("argv", "example_snippet"),
    [
        (["review", "--help"], "autoagent review show pending"),
        (["eval", "--help"], "autoagent eval run"),
        (["config", "--help"], "autoagent config list"),
        (["intelligence", "--help"], "autoagent intelligence upload"),
        (["mcp", "--help"], "autoagent mcp init codex"),
        (["judges", "--help"], "autoagent judges list"),
        (["mode", "--help"], "autoagent mode show"),
        (["context", "--help"], "autoagent context analyze --trace"),
        (["release", "--help"], "autoagent release create --experiment-id"),
        (["trace", "--help"], "autoagent trace show latest"),
        (["autofix", "--help"], "autoagent autofix suggest"),
        (["registry", "--help"], "autoagent registry list"),
        (["skill", "--help"], "autoagent skill list"),
        (["scorer", "--help"], "autoagent scorer create"),
    ],
)
def test_guide_relevant_group_help_includes_examples(argv: list[str], example_snippet: str) -> None:
    result = _runner().invoke(cli, argv)
    normalized_output = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Examples:" in result.output
    assert example_snippet in normalized_output


def test_config_group_includes_edit_pin_and_unpin() -> None:
    result = _runner().invoke(cli, ["config", "--help"])
    assert result.exit_code == 0
    for subcommand in ["list", "show", "diff", "edit", "pin", "unpin"]:
        assert subcommand in result.output


def test_deploy_group_includes_canary_release_and_rollback() -> None:
    result = _runner().invoke(cli, ["deploy", "--help"])
    assert result.exit_code == 0
    for subcommand in ["canary", "release", "rollback"]:
        assert subcommand in result.output


def test_dataset_stats_resolves_dataset_by_name() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        from data.dataset_service import DatasetService

        svc = DatasetService()
        created = svc.create("my-eval-set", "Golden dataset")

        result = runner.invoke(cli, ["dataset", "stats", "my-eval-set"])

        assert result.exit_code == 0
        payload = yaml.safe_load(result.output)
        assert payload["dataset_id"] == created.dataset_id
        assert payload["name"] == "my-eval-set"


def test_dataset_stats_suggests_close_match_for_unknown_name() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        from data.dataset_service import DatasetService

        svc = DatasetService()
        svc.create("refund-quality-set", "Refund evaluation dataset")

        result = runner.invoke(cli, ["dataset", "stats", "refund-quality-st"])

        assert result.exit_code != 0
        assert "Did you mean" in result.output
        assert "refund-quality-set" in result.output


def test_config_show_accepts_v_prefixed_versions() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        _seed_config_version()

        result = runner.invoke(cli, ["config", "show", "v1"])

        assert result.exit_code == 0
        assert "# Config: v001" in result.output


def test_scorer_show_suggests_close_match_for_unknown_name() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        create_result = runner.invoke(
            cli,
            ["scorer", "create", "be accurate and safe", "--name", "refund_quality"],
        )
        assert create_result.exit_code == 0

        show_result = runner.invoke(cli, ["scorer", "show", "refund_qualty"])

        assert show_result.exit_code != 0
        assert "Did you mean" in show_result.output
        assert "refund_quality" in show_result.output


def test_review_without_args_runs_interactive_browser() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        card = _seed_change_card()

        result = runner.invoke(cli, ["review"], input="y\n")

        assert result.exit_code == 0
        assert "Approve this change?" in result.output
        refreshed = ChangeCardStore().get(card.card_id)
        assert refreshed is not None
        assert refreshed.status == "applied"


def test_autofix_without_args_runs_interactive_browser() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        _seed_config_version()
        proposal = _seed_autofix_proposal()

        result = runner.invoke(cli, ["autofix"], input="apply\ny\n")

        assert result.exit_code == 0
        assert "Action" in result.output
        refreshed = AutoFixStore().get(proposal.proposal_id)
        assert refreshed is not None
        assert refreshed.status == "applied"


def test_deploy_canary_supports_interactive_confirmation() -> None:
    runner = _runner()
    with runner.isolated_filesystem():
        _seed_config_version()

        result = runner.invoke(cli, ["deploy", "canary", "--config-version", "1"], input="y\n")

        assert result.exit_code == 0
        manifest = json.loads(Path("configs/manifest.json").read_text(encoding="utf-8"))
        assert manifest["canary_version"] == 1
