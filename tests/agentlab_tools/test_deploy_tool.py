"""Tests for ``cli.workbench_app.agentlab_tools.deploy_tool.DeployTool`` (R7.B.3).

Mirrors the strategy used by ``test_eval_tool.py``: monkeypatch
``cli.commands.deploy.run_deploy_in_process`` with a *signature-preserving*
stub so the base class's ``inspect.signature``-driven arg stripping sees the
real parameter names. A stub declared with ``**kwargs`` would have all real
args stripped before the call.

Real deploy logic is never invoked; each test runs in microseconds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cli.tools.base import ToolContext


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


def _ok_result(**overrides: Any):
    """Build a default :class:`DeployRunResult` for stubs to return."""
    from cli.commands.deploy import DeployRunResult

    defaults = dict(
        attempt_id="att_test",
        deployment_id="dep_test",
        verdict="approved",
        status="ok",
        failure_reason=None,
    )
    defaults.update(overrides)
    return DeployRunResult(**defaults)


def _make_deploy_stub(records: list[dict[str, Any]], result_factory=_ok_result):
    """Build a stub with the SAME signature as ``run_deploy_in_process``.

    The base class strips args by matching on the wrapped function's parameter
    names (via :func:`inspect.signature`). A stub declared with only ``**kwargs``
    would have all real args stripped, so we mirror the real signature
    explicitly.
    """

    def stub(
        *,
        workflow: str | None = None,
        config_version: int | None = None,
        strategy: str = "canary",
        configs_dir: str | None = None,
        db: str | None = None,
        target: str = "agentlab",
        dry_run: bool = False,
        acknowledge: bool = False,
        auto_review: bool = False,
        force_deploy_degraded: bool = False,
        force_reason: str | None = None,
        attempt_id: str | None = None,
        release_experiment_id: str | None = None,
        strict_live: bool = False,
        on_event,
        text_writer=None,
    ):
        records.append(
            dict(
                workflow=workflow,
                config_version=config_version,
                strategy=strategy,
                configs_dir=configs_dir,
                db=db,
                target=target,
                dry_run=dry_run,
                acknowledge=acknowledge,
                auto_review=auto_review,
                force_deploy_degraded=force_deploy_degraded,
                force_reason=force_reason,
                attempt_id=attempt_id,
                release_experiment_id=release_experiment_id,
                strict_live=strict_live,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


# --------------------------------------------------------------------------
# Schema / metadata
# --------------------------------------------------------------------------


def test_name_and_schema_shape() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    assert tool.name == "Deploy"
    schema = tool.input_schema
    assert schema["type"] == "object"
    props = schema["properties"]
    # All 14 model-visible domain args should be present.
    expected = {
        "workflow",
        "config_version",
        "strategy",
        "configs_dir",
        "db",
        "target",
        "dry_run",
        "acknowledge",
        "auto_review",
        "force_deploy_degraded",
        "force_reason",
        "attempt_id",
        "release_experiment_id",
        "strict_live",
    }
    assert expected.issubset(set(props.keys()))
    assert len(props) == 14
    # Plumbing kwargs MUST NOT appear in the model-facing schema.
    assert "on_event" not in props
    assert "text_writer" not in props


def test_strategy_is_enum_in_schema() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    strategy = tool.input_schema["properties"]["strategy"]
    assert "enum" in strategy
    assert "canary" in strategy["enum"]


def test_description_warns_about_mutation() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    desc = tool.description
    assert isinstance(desc, str)
    assert len(desc) > 40
    lowered = desc.lower()
    assert any(token in lowered for token in ("production", "mutate", "deploy"))


def test_not_read_only() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    assert tool.read_only is False


# --------------------------------------------------------------------------
# Permission action — strategy-aware
# --------------------------------------------------------------------------


def test_permission_action_default_strategy() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    assert tool.permission_action({}) == "tool:Deploy:canary"


def test_permission_action_with_strategy() -> None:
    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    assert tool.permission_action({"strategy": "immediate"}) == "tool:Deploy:immediate"


# --------------------------------------------------------------------------
# Dispatch — argument forwarding
# --------------------------------------------------------------------------


def test_run_forwards_strategy_and_attempt_id(monkeypatch, tmp_path: Path) -> None:
    records: list[dict[str, Any]] = []
    stub = _make_deploy_stub(records)
    monkeypatch.setattr("cli.commands.deploy.run_deploy_in_process", stub)

    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    result = tool.run(
        {"strategy": "immediate", "attempt_id": "att_x"}, _ctx(tmp_path)
    )

    assert result.ok
    assert records[0]["strategy"] == "immediate"
    assert records[0]["attempt_id"] == "att_x"
    # on_event auto-injected.
    assert callable(records[0]["on_event"])
    assert records[0]["text_writer"] is None


def test_run_strips_unknown_args(monkeypatch, tmp_path: Path) -> None:
    records: list[dict[str, Any]] = []
    stub = _make_deploy_stub(records)
    monkeypatch.setattr("cli.commands.deploy.run_deploy_in_process", stub)

    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    result = tool.run({"bogus": 1, "strategy": "canary"}, _ctx(tmp_path))

    assert result.ok
    assert "bogus" not in records[0]
    assert records[0]["strategy"] == "canary"


# --------------------------------------------------------------------------
# Result shaping
# --------------------------------------------------------------------------


def test_run_returns_jsonsafe_content(monkeypatch, tmp_path: Path) -> None:
    def stub(**_kwargs):
        return _ok_result(
            attempt_id="att_a",
            deployment_id="dep_a",
            verdict="approved",
            status="ok",
        )

    monkeypatch.setattr("cli.commands.deploy.run_deploy_in_process", stub)

    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok
    assert isinstance(result.content, dict)
    # No tuples should leak through; all values JSON-safe.
    for value in result.content.values():
        assert not isinstance(value, tuple)
    assert result.content["attempt_id"] == "att_a"
    assert result.content["deployment_id"] == "dep_a"
    assert result.content["status"] == "ok"


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


def test_run_returns_failure_on_mock_fallback_error(monkeypatch, tmp_path: Path) -> None:
    from cli.strict_live import MockFallbackError

    def stub(**_kwargs):
        raise MockFallbackError(["x"])

    monkeypatch.setattr("cli.commands.deploy.run_deploy_in_process", stub)

    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is False
    assert "MockFallbackError" in str(result.content)


def test_run_returns_failure_on_runtime_error(monkeypatch, tmp_path: Path) -> None:
    def stub(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("cli.commands.deploy.run_deploy_in_process", stub)

    from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool

    tool = DeployTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is False
    assert "RuntimeError" in str(result.content)
    assert "boom" in str(result.content)


# --------------------------------------------------------------------------
# Registration helper
# --------------------------------------------------------------------------


def test_register_agentlab_tools_adds_deploy_and_eval() -> None:
    from cli.tools.registry import ToolRegistry
    from cli.workbench_app.agentlab_tools import register_agentlab_tools

    registry = ToolRegistry()
    register_agentlab_tools(registry)
    assert registry.has("EvalRun")
    assert registry.has("Deploy")
