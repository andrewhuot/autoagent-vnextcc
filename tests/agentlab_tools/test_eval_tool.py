"""Tests for ``cli.workbench_app.agentlab_tools.eval_tool.EvalRunTool`` (R7.B.2).

The strategy is to monkeypatch ``cli.commands.eval.run_eval_in_process`` with
a stub before each ``EvalRunTool().run(...)``. Because the tool's
``_in_process_fn`` looks up the symbol fresh on every ``.run()`` call (no
module-load cached reference), patching post-construction is safe and the
tool picks up the stub.

Real eval logic is never invoked; each test runs in microseconds.
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
    """Build a default :class:`EvalRunResult` for stubs to return."""
    from cli.commands.eval import EvalRunResult

    defaults = dict(
        run_id="er_test",
        config_path="cfg.yaml",
        mode="mock",
        status="ok",
        composite=0.85,
        warnings=(),
        artifacts=("a.json",),
        score_payload=None,
    )
    defaults.update(overrides)
    return EvalRunResult(**defaults)


# --------------------------------------------------------------------------
# Schema / metadata
# --------------------------------------------------------------------------


def test_name_and_schema_shape() -> None:
    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    assert tool.name == "EvalRun"
    schema = tool.input_schema
    assert schema["type"] == "object"
    props = schema["properties"]
    # All 11 model-visible domain args should be present; require at least 8.
    assert len(props) >= 8
    # Plumbing kwargs MUST NOT appear in the model-facing schema.
    assert "on_event" not in props
    assert "text_writer" not in props


def test_description_is_nonempty_and_mentions_cost() -> None:
    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    desc = tool.description
    assert isinstance(desc, str)
    assert len(desc) > 40
    lowered = desc.lower()
    # Should warn the model that this isn't free.
    assert any(token in lowered for token in ("token", "cost", "runs", "writes"))


def test_permission_action_uses_tool_name() -> None:
    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    assert tool.permission_action({}) == "tool:EvalRun"


def test_not_read_only() -> None:
    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    assert tool.read_only is False


# --------------------------------------------------------------------------
# Dispatch — argument forwarding
# --------------------------------------------------------------------------


def _make_signature_preserving_stub(
    calls: list[dict[str, Any]], result_factory=_ok_result
):
    """Build a stub with the SAME signature as ``run_eval_in_process``.

    The base class strips args by matching on the wrapped function's
    parameter names (via :func:`inspect.signature`). A stub declared with
    only ``**kwargs`` would have all real args stripped, so we mirror the
    real signature explicitly.
    """

    def stub(
        *,
        config_path: str | None = None,
        suite: str | None = None,
        category: str | None = None,
        dataset: str | None = None,
        dataset_split: str = "all",
        output_path: str | None = None,
        instruction_overrides_path: str | None = None,
        real_agent: bool = False,
        force_mock: bool = False,
        require_live: bool = False,
        strict_live: bool = False,
        on_event,
        text_writer=None,
    ):
        calls.append(
            dict(
                config_path=config_path,
                suite=suite,
                category=category,
                dataset=dataset,
                dataset_split=dataset_split,
                output_path=output_path,
                instruction_overrides_path=instruction_overrides_path,
                real_agent=real_agent,
                force_mock=force_mock,
                require_live=require_live,
                strict_live=strict_live,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


def test_run_forwards_config_path_arg(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    stub = _make_signature_preserving_stub(calls)
    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    result = tool.run({"config_path": "cfg.yaml"}, _ctx(tmp_path))

    assert result.ok
    assert calls[0]["config_path"] == "cfg.yaml"
    # on_event was auto-injected.
    assert callable(calls[0]["on_event"])
    # text_writer auto-injected as None.
    assert calls[0]["text_writer"] is None


def test_run_forwards_all_domain_args(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    stub = _make_signature_preserving_stub(calls)
    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    full_input = {
        "config_path": "cfg.yaml",
        "suite": "core",
        "category": "safety",
        "dataset": "my-dataset",
        "dataset_split": "train",
        "output_path": "out.json",
        "instruction_overrides_path": "ovr.yaml",
        "real_agent": True,
        "force_mock": False,
        "require_live": True,
        "strict_live": True,
    }

    tool = EvalRunTool()
    result = tool.run(full_input, _ctx(tmp_path))

    assert result.ok
    received = calls[0]
    for key, value in full_input.items():
        assert received[key] == value, f"arg {key!r} not forwarded correctly"


def test_run_strips_unknown_args(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    stub = _make_signature_preserving_stub(calls)
    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    result = tool.run({"bogus": 1, "config_path": "cfg.yaml"}, _ctx(tmp_path))

    assert result.ok
    # The stub's signature has no ``bogus`` arg — the base must have stripped
    # it before calling, otherwise the call would have raised TypeError and
    # the result would be ok=False.
    assert "bogus" not in calls[0]
    assert calls[0]["config_path"] == "cfg.yaml"


# --------------------------------------------------------------------------
# Result shaping
# --------------------------------------------------------------------------


def test_run_returns_jsonsafe_content(monkeypatch, tmp_path: Path) -> None:
    def stub(**_kwargs):
        return _ok_result(warnings=("w1", "w2"), artifacts=("a.json",))

    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok
    assert isinstance(result.content, dict)
    # Tuples must be coerced to lists by the base's _to_jsonsafe.
    assert result.content["warnings"] == ["w1", "w2"]
    assert result.content["artifacts"] == ["a.json"]


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


def test_run_returns_failure_on_mock_fallback_error(monkeypatch, tmp_path: Path) -> None:
    from cli.strict_live import MockFallbackError

    def stub(**_kwargs):
        raise MockFallbackError(["no key"])

    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is False
    assert "MockFallbackError" in str(result.content)


def test_run_returns_failure_on_runtime_error(monkeypatch, tmp_path: Path) -> None:
    def stub(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("cli.commands.eval.run_eval_in_process", stub)

    from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool

    tool = EvalRunTool()
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is False
    assert "RuntimeError" in str(result.content)
    assert "boom" in str(result.content)


# --------------------------------------------------------------------------
# Registration helper
# --------------------------------------------------------------------------


def test_register_agentlab_tools_adds_eval_run() -> None:
    from cli.tools.registry import ToolRegistry
    from cli.workbench_app.agentlab_tools import register_agentlab_tools

    registry = ToolRegistry()
    register_agentlab_tools(registry)
    assert registry.has("EvalRun")
