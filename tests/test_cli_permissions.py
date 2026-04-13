"""Tests for Stream B permissions modes and command gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
import yaml

from deployer import Deployer
from logger import ConversationStore
from optimizer.change_card import ProposedChangeCard, ChangeCardStore
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def _write_settings(root: Path, *, mode: str, rules: dict[str, list[str]] | None = None) -> Path:
    """Write workspace settings with a permissions block."""
    settings_path = root / ".agentlab" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {
                    "mode": mode,
                    "rules": rules or {},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return settings_path


def _seed_pending_change_card(root: Path) -> ProposedChangeCard:
    """Persist one pending change card for review-apply tests."""
    card = ProposedChangeCard(
        title="Tighten billing policy",
        why="Reduce misroutes for billing conversations.",
    )
    store = ChangeCardStore(db_path=str(root / ".agentlab" / "change_cards.db"))
    store.save(card)
    return card


def _seed_candidate_config(root: Path) -> int:
    """Persist one deployable non-active config version for permission tests."""
    store = ConversationStore(db_path=str(root / "conversations.db"))
    deployer = Deployer(configs_dir=str(root / "configs"), store=store)
    config = yaml.safe_load((root / "configs" / "v001.yaml").read_text(encoding="utf-8"))
    config["model"] = "permissions-candidate-v2"
    saved = deployer.version_manager.save_version(config, scores={"composite": 0.88}, status="candidate")
    return saved.version


def test_permission_modes_define_expected_default_rules(tmp_path: Path) -> None:
    """Each mode should resolve the core action classes consistently."""
    from cli.permissions import PermissionManager

    default_manager = PermissionManager(root=tmp_path)
    assert default_manager.decision_for("config.write") == "ask"
    assert default_manager.decision_for("deploy.canary") == "ask"

    _write_settings(tmp_path, mode="plan")
    plan_manager = PermissionManager(root=tmp_path)
    assert plan_manager.decision_for("config.write") == "deny"
    assert plan_manager.decision_for("memory.write") == "deny"

    _write_settings(tmp_path, mode="acceptEdits")
    accept_edits_manager = PermissionManager(root=tmp_path)
    assert accept_edits_manager.decision_for("config.write") == "allow"
    assert accept_edits_manager.decision_for("memory.write") == "allow"
    assert accept_edits_manager.decision_for("deploy.canary") == "ask"
    assert accept_edits_manager.decision_for("review.apply") == "ask"

    _write_settings(tmp_path, mode="dontAsk")
    dont_ask_manager = PermissionManager(root=tmp_path)
    assert dont_ask_manager.decision_for("config.write") == "allow"
    assert dont_ask_manager.decision_for("deploy.canary") == "allow"


def test_explicit_rules_override_mode_defaults(tmp_path: Path) -> None:
    """Explicit allow/ask/deny rules should win over the selected mode."""
    from cli.permissions import PermissionManager

    _write_settings(
        tmp_path,
        mode="acceptEdits",
        rules={
            "allow": ["deploy.canary"],
            "deny": ["config.write"],
        },
    )

    manager = PermissionManager(root=tmp_path)
    assert manager.decision_for("deploy.canary") == "allow"
    assert manager.decision_for("config.write") == "deny"
    assert manager.decision_for("memory.write") == "allow"


def test_deploy_asks_before_risky_action_in_default_mode(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deploy should still prompt in the default permission mode."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        candidate_version = _seed_candidate_config(Path("."))

        prompts: list[str] = []

        def _confirm(text: str, abort: bool = False, default: bool = False) -> bool:
            prompts.append(text)
            return True

        monkeypatch.setattr("runner.click.confirm", _confirm)
        result = runner.invoke(cli, ["deploy", "--strategy", "canary"])

        assert result.exit_code == 0, result.output
        assert prompts
        assert f"Deploy v{candidate_version:03d}" in prompts[0]


def test_deploy_skips_prompt_in_dont_ask_mode(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trusted automation mode should bypass interactive deploy confirmation."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        _seed_candidate_config(Path("."))
        _write_settings(Path("."), mode="dontAsk")

        def _unexpected_confirm(*args, **kwargs):  # pragma: no cover - assertion helper
            raise AssertionError("click.confirm should not be called in dontAsk mode")

        monkeypatch.setattr("runner.click.confirm", _unexpected_confirm)
        result = runner.invoke(cli, ["deploy", "--strategy", "canary"])

        assert result.exit_code == 0, result.output
        assert "canary" in result.output.lower()


def test_deploy_auto_review_dry_run_keeps_review_cards_pending(runner: CliRunner) -> None:
    """A dry-run auto-review deployment should preview without approving pending cards."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        _seed_candidate_config(Path("."))
        card = _seed_pending_change_card(Path("."))

        result = runner.invoke(cli, ["deploy", "--auto-review", "--yes", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output

        store = ChangeCardStore(db_path=".agentlab/change_cards.db")
        reloaded = store.get(card.card_id)
        assert reloaded is not None
        assert reloaded.status == "pending"


def test_review_apply_uses_permission_gate(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applying a review card should route through the shared approval framework."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        card = _seed_pending_change_card(Path("."))

        prompts: list[str] = []

        def _confirm(text: str, abort: bool = False, default: bool = False) -> bool:
            prompts.append(text)
            return True

        monkeypatch.setattr("runner.click.confirm", _confirm)
        result = runner.invoke(cli, ["review", "apply", card.card_id])

        assert result.exit_code == 0, result.output
        assert prompts
        assert card.card_id in result.output


def test_review_apply_pending_resolves_selector(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`review apply pending` should resolve the newest pending change card."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        card = _seed_pending_change_card(Path("."))

        prompts: list[str] = []

        def _confirm(text: str, abort: bool = False, default: bool = False) -> bool:
            del abort, default
            prompts.append(text)
            return True

        monkeypatch.setattr("runner.click.confirm", _confirm)
        result = runner.invoke(cli, ["review", "apply", "pending"])

        assert result.exit_code == 0, result.output
        assert prompts
        assert card.card_id in result.output


def test_review_export_pending_resolves_selector(runner: CliRunner) -> None:
    """`review export pending` should resolve the newest pending change card."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output
        card = _seed_pending_change_card(Path("."))

        result = runner.invoke(cli, ["review", "export", "pending"])

        assert result.exit_code == 0, result.output
        assert card.title in result.output
        assert "# Proposed Change" in result.output


def test_permissions_show_and_set_surface_workspace_mode(runner: CliRunner) -> None:
    """The permissions command should make workspace confirmation mode discoverable."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        show_result = runner.invoke(cli, ["permissions", "show"])
        set_result = runner.invoke(cli, ["permissions", "set", "acceptEdits"])

        assert show_result.exit_code == 0, show_result.output
        assert "default" in show_result.output
        assert set_result.exit_code == 0, set_result.output

        settings = json.loads((Path(".agentlab") / "settings.json").read_text(encoding="utf-8"))
        assert settings["permissions"]["mode"] == "acceptEdits"
