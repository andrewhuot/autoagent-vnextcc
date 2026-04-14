"""T20: Verify `agentlab` defaults to the workbench app and --classic opts out.

The default entry rule is the contract between runner.py's root Click group
and the new cli.workbench_app loop:

- ``agentlab`` with no subcommand on a TTY launches ``run_workbench_app``.
- ``agentlab --classic`` falls back to the pre-existing ``cli.repl.run_shell``.
- Subcommands (e.g. ``agentlab status``) are unaffected by ``--classic``.

The tests monkeypatch the launch helpers so they don't actually block on
``input()``. ``_is_tty`` is also patched to True so CliRunner's non-TTY
stdin doesn't short-circuit to the ``status`` fallback branch.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner

import runner as runner_module


class _Spy:
    """Record a single invocation + its kwargs."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))

    @property
    def called(self) -> bool:
        return bool(self.calls)


@pytest.fixture
def stub_workspace(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Pretend a workspace was discovered so the TTY branch runs."""

    class _Ws:
        workspace_label = "test-ws"
        root = "/tmp/fake-ws"

    ws = _Ws()
    monkeypatch.setattr(
        runner_module,
        "_enter_discovered_workspace",
        lambda _name: ws,
    )
    return ws


@pytest.fixture
def force_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "_is_tty", lambda: True)


def test_default_entry_launches_workbench(
    monkeypatch: pytest.MonkeyPatch,
    stub_workspace: Any,
    force_tty: None,
) -> None:
    launch = _Spy()
    run_shell = _Spy()
    monkeypatch.setattr("cli.workbench_app.app.launch_workbench", launch)
    monkeypatch.setattr("cli.repl.run_shell", run_shell)

    result = CliRunner().invoke(runner_module.cli, [])

    assert result.exit_code == 0, result.output
    assert launch.called, "default entry should launch the workbench app"
    assert not run_shell.called, "run_shell must not fire on default path"
    # The helper is called positionally with the workspace.
    assert launch.calls[0][0][0] is stub_workspace


def test_classic_flag_launches_repl(
    monkeypatch: pytest.MonkeyPatch,
    stub_workspace: Any,
    force_tty: None,
) -> None:
    launch = _Spy()
    run_shell = _Spy()
    monkeypatch.setattr("cli.workbench_app.app.launch_workbench", launch)
    monkeypatch.setattr("cli.repl.run_shell", run_shell)

    result = CliRunner().invoke(runner_module.cli, ["--classic"])

    assert result.exit_code == 0, result.output
    assert run_shell.called, "--classic should launch the classic REPL"
    assert not launch.called, "workbench app must not fire with --classic"
    assert run_shell.calls[0][0][0] is stub_workspace


def test_classic_flag_recorded_in_context(
    monkeypatch: pytest.MonkeyPatch,
    stub_workspace: Any,
    force_tty: None,
) -> None:
    """Subcommands can inspect ``ctx.obj['classic']`` if they ever need to."""
    captured: dict[str, Any] = {}

    import click

    @runner_module.cli.command("_probe", hidden=True)
    @click.pass_context
    def _probe(ctx: click.Context) -> None:
        captured["classic"] = ctx.obj.get("classic")

    try:
        result = CliRunner().invoke(runner_module.cli, ["--classic", "_probe"])
        assert result.exit_code == 0, result.output
        assert captured.get("classic") is True
    finally:
        # Clean up the probe so it doesn't leak into other tests.
        del runner_module.cli.commands["_probe"]


def test_subcommand_ignores_classic_flag(
    monkeypatch: pytest.MonkeyPatch,
    stub_workspace: Any,
    force_tty: None,
) -> None:
    """Passing --classic with an explicit subcommand does not launch either shell."""
    launch = _Spy()
    run_shell = _Spy()
    monkeypatch.setattr("cli.workbench_app.app.launch_workbench", launch)
    monkeypatch.setattr("cli.repl.run_shell", run_shell)

    import click

    sentinel: dict[str, bool] = {"ran": False}

    @runner_module.cli.command("_probe2", hidden=True)
    def _probe2() -> None:
        sentinel["ran"] = True

    try:
        result = CliRunner().invoke(runner_module.cli, ["--classic", "_probe2"])
        assert result.exit_code == 0, result.output
        assert sentinel["ran"]
        assert not launch.called
        assert not run_shell.called
    finally:
        del runner_module.cli.commands["_probe2"]


def test_no_workspace_no_tty_falls_back_to_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-TTY invocation without a workspace still takes the old status path."""
    monkeypatch.setattr(runner_module, "_is_tty", lambda: False)
    monkeypatch.setattr(
        runner_module,
        "_enter_discovered_workspace",
        lambda _name: None,
    )
    launch = _Spy()
    run_shell = _Spy()
    monkeypatch.setattr("cli.workbench_app.app.launch_workbench", launch)
    monkeypatch.setattr("cli.repl.run_shell", run_shell)

    result = CliRunner().invoke(runner_module.cli, [])

    # The fallback is `ctx.invoke(status, ...)` which may or may not exit 0
    # depending on the environment, but it must never spawn an interactive
    # shell on a non-TTY.
    assert not launch.called
    assert not run_shell.called


def test_launch_workbench_helper_wires_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`launch_workbench` creates a SessionStore + session before calling run_workbench_app."""
    from cli.workbench_app import app as app_module

    captured: dict[str, Any] = {}

    def _fake_run(workspace: Any, **kwargs: Any) -> app_module.StubAppResult:
        captured["workspace"] = workspace
        captured["kwargs"] = kwargs
        return app_module.StubAppResult(lines_read=0, exited_via="eof")

    monkeypatch.setattr(app_module, "run_workbench_app", _fake_run)

    class _Ws:
        root = tmp_path

    ws = _Ws()
    result = app_module.launch_workbench(ws, show_banner=False)

    assert result.exited_via == "eof"
    assert captured["workspace"] is ws
    # Session + store both wired with a real, non-None persistent store.
    assert captured["kwargs"]["session_store"] is not None
    assert captured["kwargs"]["session"] is not None
    assert captured["kwargs"]["show_banner"] is False


def test_launch_workbench_without_workspace_uses_ephemeral_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No workspace → no persistent store, but the loop still runs."""
    from cli.workbench_app import app as app_module

    captured: dict[str, Any] = {}

    def _fake_run(workspace: Any, **kwargs: Any) -> app_module.StubAppResult:
        captured["workspace"] = workspace
        captured["kwargs"] = kwargs
        return app_module.StubAppResult(lines_read=0, exited_via="eof")

    monkeypatch.setattr(app_module, "run_workbench_app", _fake_run)

    result = app_module.launch_workbench(None, show_banner=False)

    assert result.exited_via == "eof"
    assert captured["workspace"] is None
    assert captured["kwargs"]["session_store"] is None
    # An ephemeral in-memory session is always handed to the loop.
    session = captured["kwargs"]["session"]
    assert session is not None
    assert session.title == "ephemeral"
