"""Tests for `agentlab eval dataset bootstrap` (R5 Slice B.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from runner import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_card_markdown() -> str:
    """Render a reasonably rich card to markdown so the loader can parse it."""
    from agent_card.renderer import render_to_markdown
    from agent_card.schema import (
        AgentCardModel,
        RoutingRuleEntry,
        SubAgentSection,
        ToolEntry,
    )

    card = AgentCardModel(
        name="test_agent",
        description="Test agent for bootstrap CLI",
        instructions="Help customers.",
        routing_rules=[
            RoutingRuleEntry(target="support", keywords=["help", "issue", "account"]),
            RoutingRuleEntry(target="orders", keywords=["order", "shipping"]),
        ],
        tools=[
            ToolEntry(name="faq_lookup", description="Look up FAQ"),
            ToolEntry(name="orders_db", description="Query orders database"),
        ],
        sub_agents=[
            SubAgentSection(
                name="support",
                instructions="Handle complaints and general inquiries.",
            ),
        ],
    )
    return render_to_markdown(card)


@pytest.fixture(autouse=True)
def _force_fake_embedder(monkeypatch):
    monkeypatch.setenv("AGENTLAB_EMBEDDER", "fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


@pytest.fixture
def card_path(tmp_path):
    path = tmp_path / "card.md"
    path.write_text(_make_card_markdown(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_bootstrap_writes_yaml(tmp_path, card_path):
    out_path = tmp_path / "bootstrapped.yaml"
    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "bootstrap",
            "--card", str(card_path),
            "--target", "5",
            "--output", str(out_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert out_path.exists()

    data = yaml.safe_load(out_path.read_text())
    assert "cases" in data
    assert len(data["cases"]) == 5
    ids = [c["id"] for c in data["cases"]]
    assert len(set(ids)) == 5


def test_cli_bootstrap_requires_card_and_target(tmp_path):
    r = CliRunner().invoke(cli, ["eval", "dataset", "bootstrap"])
    assert r.exit_code != 0
    # Either --card or --target is missing.
    assert "card" in r.output.lower() or "target" in r.output.lower()


def test_cli_bootstrap_refuses_overwrite_without_force(tmp_path, card_path):
    out_path = tmp_path / "already_here.yaml"
    out_path.write_text("cases: []\n", encoding="utf-8")

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "bootstrap",
            "--card", str(card_path),
            "--target", "3",
            "--output", str(out_path),
        ],
    )
    assert r.exit_code != 0
    assert "overwrite" in r.output.lower() or "force" in r.output.lower()


def test_cli_bootstrap_force_overwrites(tmp_path, card_path):
    out_path = tmp_path / "existing.yaml"
    out_path.write_text("cases: []\n", encoding="utf-8")

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "bootstrap",
            "--card", str(card_path),
            "--target", "4",
            "--output", str(out_path),
            "--force",
        ],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(out_path.read_text())
    assert len(data["cases"]) == 4


def test_cli_bootstrap_summary_contains_counts(tmp_path, card_path):
    out_path = tmp_path / "out.yaml"
    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "bootstrap",
            "--card", str(card_path),
            "--target", "6",
            "--output", str(out_path),
        ],
    )
    assert r.exit_code == 0, r.output
    # Summary includes candidate count + selected count + output path.
    assert "Candidates generated" in r.output
    assert "Selected" in r.output
    assert str(out_path) in r.output


def test_cli_bootstrap_strict_live_flag_propagates(tmp_path, card_path, monkeypatch):
    """With a stubbed bootstrap, confirm the --strict-live flag is forwarded."""
    # Monkeypatch the bootstrap function used inside the CLI module to capture
    # kwargs while still returning a valid report.
    import cli.commands.dataset as dataset_cli
    from evals.dataset import BootstrapReport

    captured: dict = {}

    def _fake_bootstrap(card, target, embedder, **kwargs):
        captured["target"] = target
        captured.update(kwargs)
        return BootstrapReport(cases=[], selected_from_candidate_count=0, target=0)

    monkeypatch.setattr(dataset_cli, "_bootstrap_impl", _fake_bootstrap, raising=False)

    out_path = tmp_path / "live.yaml"
    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "bootstrap",
            "--card", str(card_path),
            "--target", "2",
            "--output", str(out_path),
            "--strict-live",
        ],
    )
    # Even if bootstrap is a no-op the CLI should succeed (empty cases list).
    assert r.exit_code == 0, r.output
    assert captured.get("strict_live") is True
