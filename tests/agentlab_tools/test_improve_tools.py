"""Tests for the five Improve* AgentLab tools (R7.B.4).

Mirrors the patterns from ``test_eval_tool.py`` and ``test_deploy_tool.py``:
each test monkeypatches the relevant ``cli.commands.improve.run_improve_*_in_process``
symbol with a *signature-preserving* stub. The base class (``AgentLabTool``)
strips unknown args via :func:`inspect.signature`, so a ``**kwargs``-only stub
would have all real args dropped — every stub here mirrors the real signature
explicitly.

Real improve logic is never invoked; each test runs in microseconds.
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


# --- Result factories ------------------------------------------------------


def _ok_run_result(**overrides: Any):
    from cli.commands.improve import ImproveRunResult

    defaults = dict(
        attempt_id="att_test",
        config_path="cfg.yaml",
        eval_run_id="er_test",
        status="ok",
    )
    defaults.update(overrides)
    return ImproveRunResult(**defaults)


def _ok_list_result(**overrides: Any):
    from cli.commands.improve import ImproveListResult

    defaults = dict(
        attempts=tuple(),
        status="ok",
    )
    defaults.update(overrides)
    return ImproveListResult(**defaults)


def _ok_show_result(**overrides: Any):
    from cli.commands.improve import ImproveShowResult

    defaults = dict(
        attempt_id="att_show",
        attempt={"attempt_id": "att_show", "status": "accepted"},
        status="ok",
    )
    defaults.update(overrides)
    return ImproveShowResult(**defaults)


def _ok_diff_result(**overrides: Any):
    from cli.commands.improve import ImproveDiffResult

    defaults = dict(
        attempt_id="att_diff",
        change_description="tweak",
        config_section="prompt",
        config_diff="--- a\n+++ b\n",
        patch_bundle=None,
        score_before=0.5,
        score_after=0.7,
        status_raw="accepted",
        diff_text="--- a\n+++ b\n",
        status="ok",
    )
    defaults.update(overrides)
    return ImproveDiffResult(**defaults)


def _ok_accept_result(**overrides: Any):
    from cli.commands.improve import ImproveAcceptResult

    defaults = dict(
        attempt_id="att_accept",
        deployment_id="dep_x",
        deployed_version=3,
        strategy="canary",
        already_deployed=False,
        measurement_scheduled=True,
        status="ok",
    )
    defaults.update(overrides)
    return ImproveAcceptResult(**defaults)


# --- Signature-preserving stubs -------------------------------------------


def _make_run_stub(records: list[dict[str, Any]], result_factory=_ok_run_result):
    def stub(
        *,
        config_path: str | None = None,
        cycles: int = 1,
        mode: str | None = None,
        strict_live: bool = False,
        auto: bool = False,
        on_event,
        text_writer=None,
    ):
        records.append(
            dict(
                config_path=config_path,
                cycles=cycles,
                mode=mode,
                strict_live=strict_live,
                auto=auto,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


def _make_list_stub(records: list[dict[str, Any]], result_factory=_ok_list_result):
    def stub(
        *,
        status: str | None = None,
        reason: str | None = None,
        limit: int = 20,
        memory_db: str | None = None,
        lineage_db: str | None = None,
        on_event,
        text_writer=None,
    ):
        records.append(
            dict(
                status=status,
                reason=reason,
                limit=limit,
                memory_db=memory_db,
                lineage_db=lineage_db,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


def _make_show_stub(records: list[dict[str, Any]], result_factory=_ok_show_result):
    def stub(
        *,
        attempt_id: str,
        memory_db: str | None = None,
        lineage_db: str | None = None,
        on_event,
        text_writer=None,
    ):
        records.append(
            dict(
                attempt_id=attempt_id,
                memory_db=memory_db,
                lineage_db=lineage_db,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


def _make_diff_stub(records: list[dict[str, Any]], result_factory=_ok_diff_result):
    def stub(
        *,
        attempt_id: str,
        memory_db: str | None = None,
        on_event,
        text_writer=None,
    ):
        records.append(
            dict(
                attempt_id=attempt_id,
                memory_db=memory_db,
                on_event=on_event,
                text_writer=text_writer,
            )
        )
        return result_factory()

    return stub


def _make_accept_stub(records: list[dict[str, Any]], result_factory=_ok_accept_result):
    def stub(
        *,
        attempt_id: str,
        strategy: str = "canary",
        memory_db: str | None = None,
        lineage_db: str | None = None,
        on_event,
        text_writer=None,
        deploy_invoker=None,
    ):
        records.append(
            dict(
                attempt_id=attempt_id,
                strategy=strategy,
                memory_db=memory_db,
                lineage_db=lineage_db,
                on_event=on_event,
                text_writer=text_writer,
                deploy_invoker=deploy_invoker,
            )
        )
        return result_factory()

    return stub


# --------------------------------------------------------------------------
# ImproveRunTool
# --------------------------------------------------------------------------


class TestImproveRunTool:
    def test_improve_run_name_and_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        tool = ImproveRunTool()
        assert tool.name == "ImproveRun"
        props = tool.input_schema["properties"]
        expected = {"config_path", "cycles", "mode", "strict_live", "auto"}
        assert expected.issubset(set(props.keys()))
        assert "on_event" not in props
        assert "text_writer" not in props

    def test_improve_run_required_field_in_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        tool = ImproveRunTool()
        assert "config_path" in tool.input_schema.get("required", [])

    def test_improve_run_read_only_flag(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        assert ImproveRunTool().read_only is False

    def test_improve_run_description_nonempty(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        desc = ImproveRunTool().description
        assert isinstance(desc, str)
        assert len(desc) > 40

    def test_improve_run_run_forwards_args(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_run_in_process",
            _make_run_stub(records),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        tool = ImproveRunTool()
        result = tool.run(
            {
                "config_path": "cfg.yaml",
                "cycles": 3,
                "mode": "fast",
                "strict_live": True,
                "auto": True,
            },
            _ctx(tmp_path),
        )

        assert result.ok
        rec = records[0]
        assert rec["config_path"] == "cfg.yaml"
        assert rec["cycles"] == 3
        assert rec["mode"] == "fast"
        assert rec["strict_live"] is True
        assert rec["auto"] is True
        assert callable(rec["on_event"])
        assert rec["text_writer"] is None

    def test_improve_run_run_returns_jsonsafe_content(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_run_in_process",
            _make_run_stub([]),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        result = ImproveRunTool().run({"config_path": "cfg.yaml"}, _ctx(tmp_path))

        assert result.ok
        assert isinstance(result.content, dict)
        assert result.content["attempt_id"] == "att_test"
        assert result.content["status"] == "ok"

    def test_improve_run_run_returns_failure_on_exception(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_run_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveRunTool

        result = ImproveRunTool().run({"config_path": "cfg.yaml"}, _ctx(tmp_path))

        assert result.ok is False
        assert "RuntimeError" in str(result.content)
        assert "boom" in str(result.content)


# --------------------------------------------------------------------------
# ImproveListTool
# --------------------------------------------------------------------------


class TestImproveListTool:
    def test_improve_list_name_and_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        tool = ImproveListTool()
        assert tool.name == "ImproveList"
        props = tool.input_schema["properties"]
        expected = {"status", "reason", "limit", "memory_db", "lineage_db"}
        assert expected.issubset(set(props.keys()))
        assert "on_event" not in props
        assert "text_writer" not in props

    def test_improve_list_no_required_field(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        # ImproveList has no required args.
        required = ImproveListTool().input_schema.get("required", [])
        assert required == []

    def test_improve_list_read_only_flag(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        assert ImproveListTool().read_only is True

    def test_improve_list_run_forwards_args(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_list_in_process",
            _make_list_stub(records),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        result = ImproveListTool().run(
            {
                "status": "rejected",
                "reason": "score_regression",
                "limit": 5,
                "memory_db": "/tmp/mem.db",
                "lineage_db": "/tmp/lin.db",
            },
            _ctx(tmp_path),
        )

        assert result.ok
        rec = records[0]
        assert rec["status"] == "rejected"
        assert rec["reason"] == "score_regression"
        assert rec["limit"] == 5
        assert rec["memory_db"] == "/tmp/mem.db"
        assert rec["lineage_db"] == "/tmp/lin.db"
        assert callable(rec["on_event"])

    def test_improve_list_run_returns_jsonsafe_content(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            return _ok_list_result(
                attempts=({"attempt_id": "a1", "status": "accepted"},)
            )

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_list_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        result = ImproveListTool().run({}, _ctx(tmp_path))

        assert result.ok
        assert isinstance(result.content, dict)
        # tuple should be coerced to list.
        assert isinstance(result.content["attempts"], list)
        assert result.content["attempts"][0]["attempt_id"] == "a1"

    def test_improve_list_run_returns_failure_on_exception(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_list_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveListTool

        result = ImproveListTool().run({}, _ctx(tmp_path))

        assert result.ok is False
        assert "RuntimeError" in str(result.content)


# --------------------------------------------------------------------------
# ImproveShowTool
# --------------------------------------------------------------------------


class TestImproveShowTool:
    def test_improve_show_name_and_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        tool = ImproveShowTool()
        assert tool.name == "ImproveShow"
        props = tool.input_schema["properties"]
        expected = {"attempt_id", "memory_db", "lineage_db"}
        assert expected.issubset(set(props.keys()))
        assert "on_event" not in props
        assert "text_writer" not in props

    def test_improve_show_required_field_in_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        assert "attempt_id" in ImproveShowTool().input_schema.get("required", [])

    def test_improve_show_read_only_flag(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        assert ImproveShowTool().read_only is True

    def test_improve_show_run_forwards_args(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_show_in_process",
            _make_show_stub(records),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        result = ImproveShowTool().run(
            {
                "attempt_id": "att_show",
                "memory_db": "/tmp/m.db",
                "lineage_db": "/tmp/l.db",
            },
            _ctx(tmp_path),
        )

        assert result.ok
        rec = records[0]
        assert rec["attempt_id"] == "att_show"
        assert rec["memory_db"] == "/tmp/m.db"
        assert rec["lineage_db"] == "/tmp/l.db"

    def test_improve_show_run_returns_jsonsafe_content(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_show_in_process",
            _make_show_stub([]),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        result = ImproveShowTool().run({"attempt_id": "att_show"}, _ctx(tmp_path))

        assert result.ok
        assert isinstance(result.content, dict)
        assert result.content["attempt_id"] == "att_show"

    def test_improve_show_run_returns_failure_on_exception(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_show_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveShowTool

        result = ImproveShowTool().run({"attempt_id": "x"}, _ctx(tmp_path))

        assert result.ok is False
        assert "RuntimeError" in str(result.content)


# --------------------------------------------------------------------------
# ImproveDiffTool
# --------------------------------------------------------------------------


class TestImproveDiffTool:
    def test_improve_diff_name_and_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        tool = ImproveDiffTool()
        assert tool.name == "ImproveDiff"
        props = tool.input_schema["properties"]
        expected = {"attempt_id", "memory_db"}
        assert expected.issubset(set(props.keys()))
        assert "on_event" not in props
        assert "text_writer" not in props

    def test_improve_diff_required_field_in_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        assert "attempt_id" in ImproveDiffTool().input_schema.get("required", [])

    def test_improve_diff_read_only_flag(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        assert ImproveDiffTool().read_only is True

    def test_improve_diff_run_forwards_args(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_diff_in_process",
            _make_diff_stub(records),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        result = ImproveDiffTool().run(
            {"attempt_id": "att_diff", "memory_db": "/tmp/m.db"},
            _ctx(tmp_path),
        )

        assert result.ok
        rec = records[0]
        assert rec["attempt_id"] == "att_diff"
        assert rec["memory_db"] == "/tmp/m.db"

    def test_improve_diff_run_returns_jsonsafe_content(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            # patch_bundle is Any | None — exercise the dict branch to make sure
            # _to_jsonsafe handles nested dicts cleanly.
            return _ok_diff_result(patch_bundle={"k": [1, 2]})

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_diff_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        result = ImproveDiffTool().run({"attempt_id": "x"}, _ctx(tmp_path))

        assert result.ok
        assert isinstance(result.content, dict)
        assert result.content["attempt_id"] == "att_diff"
        assert result.content["patch_bundle"] == {"k": [1, 2]}

    def test_improve_diff_run_returns_failure_on_exception(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_diff_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveDiffTool

        result = ImproveDiffTool().run({"attempt_id": "x"}, _ctx(tmp_path))

        assert result.ok is False
        assert "RuntimeError" in str(result.content)


# --------------------------------------------------------------------------
# ImproveAcceptTool
# --------------------------------------------------------------------------


class TestImproveAcceptTool:
    def test_improve_accept_name_and_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        tool = ImproveAcceptTool()
        assert tool.name == "ImproveAccept"
        props = tool.input_schema["properties"]
        expected = {"attempt_id", "strategy", "memory_db", "lineage_db"}
        assert expected.issubset(set(props.keys()))
        assert "on_event" not in props
        assert "text_writer" not in props

    def test_improve_accept_required_field_in_schema(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        assert "attempt_id" in ImproveAcceptTool().input_schema.get("required", [])

    def test_improve_accept_read_only_flag(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        assert ImproveAcceptTool().read_only is False

    def test_improve_accept_does_not_expose_deploy_invoker(self) -> None:
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        # The deploy_invoker arg is internal plumbing (Click vs slash). It
        # MUST NOT appear in the model-facing schema.
        assert (
            "deploy_invoker"
            not in ImproveAcceptTool().input_schema["properties"]
        )

    def test_improve_accept_run_forwards_args(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_accept_in_process",
            _make_accept_stub(records),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        result = ImproveAcceptTool().run(
            {
                "attempt_id": "att_accept",
                "strategy": "immediate",
                "memory_db": "/tmp/m.db",
                "lineage_db": "/tmp/l.db",
            },
            _ctx(tmp_path),
        )

        assert result.ok
        rec = records[0]
        assert rec["attempt_id"] == "att_accept"
        assert rec["strategy"] == "immediate"
        assert rec["memory_db"] == "/tmp/m.db"
        assert rec["lineage_db"] == "/tmp/l.db"
        # deploy_invoker should remain its function default (None) because the
        # base class never sees it (not in schema, not in tool_input).
        assert rec["deploy_invoker"] is None

    def test_improve_accept_run_returns_jsonsafe_content(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "cli.commands.improve.run_improve_accept_in_process",
            _make_accept_stub([]),
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        result = ImproveAcceptTool().run(
            {"attempt_id": "att_accept"}, _ctx(tmp_path)
        )

        assert result.ok
        assert isinstance(result.content, dict)
        assert result.content["attempt_id"] == "att_accept"
        assert result.content["deployment_id"] == "dep_x"

    def test_improve_accept_run_returns_failure_on_exception(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        def stub(**_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "cli.commands.improve.run_improve_accept_in_process", stub
        )
        from cli.workbench_app.agentlab_tools.improve_tools import ImproveAcceptTool

        result = ImproveAcceptTool().run({"attempt_id": "x"}, _ctx(tmp_path))

        assert result.ok is False
        assert "RuntimeError" in str(result.content)


# --------------------------------------------------------------------------
# Cross-cutting registration
# --------------------------------------------------------------------------


def test_register_agentlab_tools_registers_all_seven() -> None:
    from cli.tools.registry import ToolRegistry
    from cli.workbench_app.agentlab_tools import register_agentlab_tools

    registry = ToolRegistry()
    register_agentlab_tools(registry)
    assert set(registry.tools) == {
        "EvalRun",
        "Deploy",
        "ImproveRun",
        "ImproveList",
        "ImproveShow",
        "ImproveDiff",
        "ImproveAccept",
    }
