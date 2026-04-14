"""Tests for /diff, /accept, /reject candidate-promotion slash commands."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest

from cli.workbench_app.config_diff_slash import (
    _handle_accept,
    _handle_diff,
    _handle_reject,
    build_accept_command,
    build_diff_command,
    build_reject_command,
)
from cli.workbench_app.slash import SlashContext
from deployer.versioning import ConfigVersionManager


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    """Seed a ``configs/`` directory with an active v1 and candidate v2."""
    configs = tmp_path / "configs"
    versions = ConfigVersionManager(configs_dir=str(configs))
    versions.save_version(
        config={"model": "gemini-2.5-flash", "routing": {"rules": []}},
        scores={"composite": 0.8},
        status="active",
    )
    versions.save_version(
        config={"model": "gemini-2.5-pro", "routing": {"rules": ["fast-path"]}},
        scores={"composite": 0.9},
        status="candidate",
    )
    return configs


@pytest.fixture
def ctx(configs_dir: Path) -> SlashContext:
    return SlashContext(meta={"configs_dir": configs_dir})


def _read_manifest(configs: Path) -> dict:
    with (configs / "manifest.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _status_of(configs: Path, version: int) -> str:
    manifest = _read_manifest(configs)
    for entry in manifest["versions"]:
        if entry["version"] == version:
            return entry["status"]
    raise AssertionError(f"version {version} missing from manifest")


# ---------------------------------------------------------------------------
# Command factories — basic metadata assertions.
# ---------------------------------------------------------------------------


def test_build_diff_command_metadata() -> None:
    cmd = build_diff_command()
    assert cmd.name == "diff"
    assert cmd.sensitive is False


def test_build_accept_command_is_sensitive() -> None:
    cmd = build_accept_command()
    assert cmd.name == "accept"
    assert cmd.sensitive is True


def test_build_reject_command_is_sensitive() -> None:
    cmd = build_reject_command()
    assert cmd.name == "reject"
    assert cmd.sensitive is True


# ---------------------------------------------------------------------------
# /diff.
# ---------------------------------------------------------------------------


def test_diff_without_args_compares_active_to_latest_candidate(
    ctx: SlashContext,
) -> None:
    result = _handle_diff(ctx)

    assert result.display == "user"
    plain = click.unstyle(result.result or "")
    assert "v001" in plain and "v002" in plain
    assert "-model: gemini-2.5-flash" in plain
    assert "+model: gemini-2.5-pro" in plain


def test_diff_self_reports_no_differences(ctx: SlashContext) -> None:
    result = _handle_diff(ctx, "v1")

    assert result.display == "system"
    assert "No differences" in (result.result or "")


def test_diff_explicit_version_shows_diff(ctx: SlashContext) -> None:
    result = _handle_diff(ctx, "2")

    plain = click.unstyle(result.result or "")
    assert "+model: gemini-2.5-pro" in plain
    assert "-model: gemini-2.5-flash" in plain


def test_diff_unknown_version_returns_system_error(ctx: SlashContext) -> None:
    result = _handle_diff(ctx, "v99")

    assert result.display == "system"
    assert "Unknown" in (result.result or "")


def test_diff_invalid_version_token_returns_system_error(
    ctx: SlashContext,
) -> None:
    result = _handle_diff(ctx, "not-a-version")

    assert result.display == "system"
    assert "Not a valid version" in (result.result or "")


def test_diff_with_no_configs_dir_returns_system_error(tmp_path: Path) -> None:
    ctx = SlashContext(meta={"configs_dir": tmp_path / "missing"})

    result = _handle_diff(ctx)

    assert result.display == "system"
    assert "configs/" in (result.result or "")


def test_diff_with_no_candidate_returns_system_error(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    versions = ConfigVersionManager(configs_dir=str(configs))
    versions.save_version(
        config={"model": "only-active"},
        scores={"composite": 0.8},
        status="active",
    )
    ctx = SlashContext(meta={"configs_dir": configs})

    result = _handle_diff(ctx)

    assert result.display == "system"
    assert "candidate" in (result.result or "")


# ---------------------------------------------------------------------------
# /accept.
# ---------------------------------------------------------------------------


def test_accept_promotes_version_and_retires_previous_active(
    ctx: SlashContext, configs_dir: Path
) -> None:
    result = _handle_accept(ctx, "v2")

    assert result.display == "user"
    manifest = _read_manifest(configs_dir)
    assert manifest["active_version"] == 2
    assert _status_of(configs_dir, 1) == "retired"
    assert _status_of(configs_dir, 2) == "active"


def test_accept_without_args_returns_usage(ctx: SlashContext) -> None:
    result = _handle_accept(ctx)

    assert result.display == "system"
    assert "Usage" in (result.result or "")


def test_accept_unknown_version_returns_system_error(ctx: SlashContext) -> None:
    result = _handle_accept(ctx, "v99")

    assert result.display == "system"
    assert "Unknown version" in (result.result or "")


# ---------------------------------------------------------------------------
# /reject.
# ---------------------------------------------------------------------------


def test_reject_marks_rolled_back_without_touching_active(
    ctx: SlashContext, configs_dir: Path
) -> None:
    result = _handle_reject(ctx, "v2")

    assert result.display == "user"
    manifest = _read_manifest(configs_dir)
    assert manifest["active_version"] == 1
    assert _status_of(configs_dir, 2) == "rolled_back"
    assert _status_of(configs_dir, 1) == "active"


def test_reject_without_args_returns_usage(ctx: SlashContext) -> None:
    result = _handle_reject(ctx)

    assert result.display == "system"
    assert "Usage" in (result.result or "")


def test_reject_unknown_version_returns_system_error(ctx: SlashContext) -> None:
    result = _handle_reject(ctx, "v99")

    assert result.display == "system"
    assert "Unknown version" in (result.result or "")
