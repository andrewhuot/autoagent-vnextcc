"""Tests for cli/harness_onboarding.py — harness.models first-run wizard."""

from __future__ import annotations

from pathlib import Path

import yaml

from cli.harness_onboarding import (
    HarnessChoice,
    RoleModel,
    needs_harness_config,
    run_harness_wizard,
    write_harness_models,
)


# ---------------------------------------------------------------------------
# needs_harness_config
# ---------------------------------------------------------------------------


def test_needs_harness_config_true_when_file_missing(tmp_path: Path) -> None:
    assert needs_harness_config(tmp_path / "agentlab.yaml") is True


def test_needs_harness_config_true_when_file_empty(tmp_path: Path) -> None:
    config = tmp_path / "agentlab.yaml"
    config.write_text("", encoding="utf-8")
    assert needs_harness_config(config) is True


def test_needs_harness_config_true_when_partial_role(tmp_path: Path) -> None:
    """A declaration without a model key is invalid — wizard must run."""
    config = tmp_path / "agentlab.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "harness": {
                    "models": {
                        "coordinator": {"provider": "anthropic"},
                        "worker": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert needs_harness_config(config) is True


def test_needs_harness_config_true_when_only_optimizer_fallback(tmp_path: Path) -> None:
    """Legacy optimizer.models inheritance is not an explicit harness decl."""
    config = tmp_path / "agentlab.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "models": [{"provider": "anthropic", "model": "claude-sonnet-4-6"}]
                }
            }
        ),
        encoding="utf-8",
    )
    assert needs_harness_config(config) is True


def test_needs_harness_config_false_when_both_roles_declared(tmp_path: Path) -> None:
    config = tmp_path / "agentlab.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "harness": {
                    "models": {
                        "coordinator": {
                            "provider": "anthropic",
                            "model": "claude-opus-4-6",
                        },
                        "worker": {
                            "provider": "anthropic",
                            "model": "claude-sonnet-4-6",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert needs_harness_config(config) is False


# ---------------------------------------------------------------------------
# run_harness_wizard + write_harness_models
# ---------------------------------------------------------------------------


def _scripted_prompt(answers: dict[str, str]):
    """Return a prompt_fn that yields answers based on a substring match in the label."""

    def prompt_fn(label: str, choices, default: str) -> str:
        lowered = label.lower()
        for key, value in answers.items():
            if key in lowered:
                return value
        return default

    return prompt_fn


def test_run_harness_wizard_returns_choice_from_answers(tmp_path: Path) -> None:
    echoed: list[str] = []
    prompt_fn = _scripted_prompt(
        {
            "provider": "anthropic",
            "coordinator model": "claude-opus-4-6",
            "worker model": "claude-sonnet-4-6",
        }
    )
    choice = run_harness_wizard(
        tmp_path / "agentlab.yaml",
        prompt_fn=prompt_fn,
        echo_fn=echoed.append,
    )
    assert isinstance(choice, HarnessChoice)
    assert choice.coordinator == RoleModel(
        provider="anthropic",
        model="claude-opus-4-6",
        api_key_env="ANTHROPIC_API_KEY",
    )
    assert choice.worker == RoleModel(
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key_env="ANTHROPIC_API_KEY",
    )
    # Should have printed a banner/header of some kind.
    assert any("harness" in line.lower() for line in echoed)


def test_run_harness_wizard_openai_defaults(tmp_path: Path) -> None:
    prompt_fn = _scripted_prompt({"provider": "openai"})
    choice = run_harness_wizard(
        tmp_path / "agentlab.yaml",
        prompt_fn=prompt_fn,
        echo_fn=lambda _: None,
    )
    assert choice.coordinator.provider == "openai"
    assert choice.coordinator.api_key_env == "OPENAI_API_KEY"
    assert choice.worker.api_key_env == "OPENAI_API_KEY"
    # Worker model defaults to the first entry (fast/cheap).
    assert choice.worker.model == "gpt-4.1-mini"


def test_run_harness_wizard_rejects_unknown_answer_and_uses_default(tmp_path: Path) -> None:
    prompt_fn = _scripted_prompt({"provider": "made-up-provider"})
    choice = run_harness_wizard(
        tmp_path / "agentlab.yaml",
        prompt_fn=prompt_fn,
        echo_fn=lambda _: None,
    )
    # Falls back to the first provider in the catalogue — anthropic.
    assert choice.coordinator.provider == "anthropic"


def test_write_harness_models_writes_keys_to_yaml(tmp_path: Path) -> None:
    config = tmp_path / "agentlab.yaml"
    choice = HarnessChoice(
        coordinator=RoleModel(
            provider="anthropic",
            model="claude-opus-4-6",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        worker=RoleModel(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    )
    write_harness_models(config, choice)

    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["harness"]["models"]["coordinator"]["provider"] == "anthropic"
    assert loaded["harness"]["models"]["coordinator"]["model"] == "claude-opus-4-6"
    assert loaded["harness"]["models"]["coordinator"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert loaded["harness"]["models"]["worker"]["model"] == "claude-sonnet-4-6"

    # After writing, needs_harness_config should flip to False.
    assert needs_harness_config(config) is False


def test_write_harness_models_preserves_unrelated_keys(tmp_path: Path) -> None:
    config = tmp_path / "agentlab.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "optimizer": {"use_mock": False, "models": [{"provider": "openai", "model": "gpt-4.1"}]},
                "deployer": {"target": "local"},
            }
        ),
        encoding="utf-8",
    )
    choice = HarnessChoice(
        coordinator=RoleModel(
            provider="google",
            model="gemini-2.5-pro",
            api_key_env="GOOGLE_API_KEY",
        ),
        worker=RoleModel(
            provider="google",
            model="gemini-2.5-flash",
            api_key_env="GOOGLE_API_KEY",
        ),
    )
    write_harness_models(config, choice)

    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    # Existing sections preserved
    assert loaded["optimizer"]["use_mock"] is False
    assert loaded["deployer"]["target"] == "local"
    # Harness section added
    assert loaded["harness"]["models"]["coordinator"]["model"] == "gemini-2.5-pro"
    assert loaded["harness"]["models"]["worker"]["model"] == "gemini-2.5-flash"


def test_write_harness_models_merges_into_existing_harness_section(tmp_path: Path) -> None:
    """Existing harness keys (e.g. harness.cap_plan) must not be clobbered."""
    config = tmp_path / "agentlab.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "harness": {
                    "cap_plan": {"max_workers": 4},
                }
            }
        ),
        encoding="utf-8",
    )
    choice = HarnessChoice(
        coordinator=RoleModel(
            provider="anthropic",
            model="claude-opus-4-6",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        worker=RoleModel(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    )
    write_harness_models(config, choice)

    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["harness"]["cap_plan"]["max_workers"] == 4
    assert loaded["harness"]["models"]["coordinator"]["provider"] == "anthropic"
