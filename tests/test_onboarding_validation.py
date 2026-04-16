"""Tests for onboarding key validation (R1.10, Part B)."""
from __future__ import annotations

from unittest.mock import patch

import click
import pytest


def test_onboarding_rejects_short_key_then_accepts_valid():
    """Simulate user pasting a short key first, then a valid one."""
    from cli import onboarding

    valid_key = "sk-" + "a" * 40
    prompts_answered = iter([
        "1",        # choice: paste OpenAI key
        "short",    # first paste: invalid (too short)
        valid_key,  # second paste: valid
    ])

    def fake_prompt(*args, **kwargs):
        return next(prompts_answered)

    with patch.object(click, "prompt", side_effect=fake_prompt), \
         patch.object(onboarding, "write_workspace_env_values") as mock_write, \
         patch.object(onboarding, "hydrate_provider_key_aliases"):
        mode, env_name = onboarding._prompt_for_provider_key()

    assert mode == "live"
    assert env_name == "OPENAI_API_KEY"
    mock_write.assert_called_once()
    call_args = mock_write.call_args[0][0]
    assert call_args["OPENAI_API_KEY"] == valid_key


def test_onboarding_aborts_after_three_bad_keys():
    """After 3 bad attempts, raise click.Abort."""
    from cli import onboarding

    prompts_answered = iter(["1", "bad1", "bad2", "bad3"])

    def fake_prompt(*args, **kwargs):
        return next(prompts_answered)

    with patch.object(click, "prompt", side_effect=fake_prompt), \
         patch.object(onboarding, "write_workspace_env_values"), \
         patch.object(onboarding, "hydrate_provider_key_aliases"):
        with pytest.raises(click.Abort):
            onboarding._prompt_for_provider_key()
