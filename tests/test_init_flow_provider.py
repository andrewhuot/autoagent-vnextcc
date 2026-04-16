"""Tests for init flow provider-key step (R1.10, Part C)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.init_flow import InitFlow


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_init_flow_force_mock_skips_provider_step(tmp_path, clean_env, capsys):
    flow = InitFlow(workspace=tmp_path, force_mock=True, skip_eval=True, skip_generate=True, interactive=False)
    result = flow.run()
    assert result.eval_mode == "mock"
    assert not any(s.startswith("provider_key:") and "saved" in s for s in result.steps_completed)


def test_init_flow_detects_existing_key(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 40)
    flow = InitFlow(workspace=tmp_path, skip_generate=True, interactive=False)
    result = flow.run()
    assert result.eval_mode == "real"


def test_init_flow_noninteractive_no_key_falls_back_to_mock(tmp_path, clean_env):
    flow = InitFlow(workspace=tmp_path, skip_generate=True, interactive=False)
    result = flow.run()
    assert result.eval_mode == "mock"
    assert any("mock" in w.lower() or "no provider" in w.lower() for w in result.warnings) or \
           any("provider_key:skipped" in s for s in result.steps_completed)


def test_init_flow_interactive_prompts_and_saves(tmp_path, clean_env, monkeypatch):
    """When interactive and no key present, prompt and save."""
    valid_key = "sk-" + "a" * 40
    prompts = iter(["1", valid_key])

    def fake_prompt(*args, **kwargs):
        return next(prompts)

    import click as _click
    with patch.object(_click, "prompt", side_effect=fake_prompt), \
         patch("cli.init_flow.write_workspace_env_values") as mock_write:
        flow = InitFlow(workspace=tmp_path, skip_generate=True, interactive=True)
        result = flow.run()

    assert result.eval_mode == "real"
    mock_write.assert_called_once()
