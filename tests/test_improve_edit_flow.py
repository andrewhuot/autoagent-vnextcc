"""Tests for `/improve accept <id> --edit` — inline edit of proposal before accept (R4.12 / C6).

Covers the handler seam in ``cli.workbench_app.improve_slash`` and the
``candidate_override_path`` kwarg on
``cli.commands.improve.run_improve_accept_in_process``.

The TextArea modal is factored behind an injectable seam
(``_prompt_yaml_edit``) so these unit tests can drive the edit flow
without standing up a Textual app. See
``cli/workbench_app/improve_slash.py::_prompt_yaml_edit`` for the
docstring explaining why.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Iterator, Sequence
from unittest.mock import patch

import pytest

from cli.workbench_app import improve_slash
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.improve_slash import build_improve_command
from cli.workbench_app.slash import SlashContext, dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def ctx(echo: _EchoCapture, tmp_path: Path) -> SlashContext:
    registry = CommandRegistry()
    c = SlashContext(echo=echo, registry=registry)
    c.meta["workspace_root"] = str(tmp_path)
    return c


def _install_improve(ctx: SlashContext, runner: Any) -> None:
    assert ctx.registry is not None
    ctx.registry.register(build_improve_command(runner=runner))


def _seed_candidate_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "candidate.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _install_lineage_view(
    ctx: SlashContext,
    attempt_id: str,
    candidate_path: Path | None,
) -> None:
    """Drop a fake lineage store into ctx.meta so the handler's --edit
    branch can look up the attempt without touching sqlite."""
    from optimizer.improvement_lineage import (
        AttemptLineageView,
        EVENT_ATTEMPT,
        LineageEvent,
    )

    events: list[LineageEvent] = []
    if candidate_path is not None:
        events.append(
            LineageEvent(
                event_id="ev1",
                attempt_id=attempt_id,
                event_type=EVENT_ATTEMPT,
                timestamp=0.0,
                payload={"candidate_config_path": str(candidate_path)},
            )
        )
    view = AttemptLineageView(attempt_id=attempt_id, events=events)

    class _FakeStore:
        def view_attempt(self, _aid: str) -> AttemptLineageView:  # type: ignore[override]
            return view

    ctx.meta["lineage_store"] = _FakeStore()


def _install_unknown_attempt_store(ctx: SlashContext) -> None:
    from optimizer.improvement_lineage import AttemptLineageView

    class _FakeStore:
        def view_attempt(self, _aid: str) -> AttemptLineageView:
            return AttemptLineageView(attempt_id="att_unknown", events=[])

    ctx.meta["lineage_store"] = _FakeStore()


def _fake_runner(
    events: Sequence[dict[str, Any]],
    *,
    record: list[dict[str, Any]] | None = None,
):
    """Fake StreamRunner — also captures kwargs forwarded by the handler.

    The real runner parses argv and injects kwargs to the in-process
    function; our fake records (args, kwargs) so tests can assert what
    the handler would have passed downstream.
    """
    calls_args: list[list[str]] = []

    def _run(args: Sequence[str], **kwargs: Any) -> Iterator[dict[str, Any]]:
        calls_args.append(list(args))
        if record is not None:
            record.append({"args": list(args), "kwargs": kwargs})
        yield from events

    _run.calls = calls_args  # type: ignore[attr-defined]
    return _run


# ---------------------------------------------------------------------------
# run_improve_accept_in_process: candidate_override_path kwarg exists
# ---------------------------------------------------------------------------


def test_run_improve_accept_has_candidate_override_path_kwarg() -> None:
    """Contract: the in-process accept function accepts
    ``candidate_override_path: Path | None`` (default None = legacy
    behavior)."""
    from cli.commands.improve import run_improve_accept_in_process

    sig = inspect.signature(run_improve_accept_in_process)
    assert "candidate_override_path" in sig.parameters
    # Default must be None so the legacy path is unchanged.
    assert sig.parameters["candidate_override_path"].default is None


def test_run_improve_accept_override_persists_new_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``candidate_override_path`` is set, the in-process accept reads
    the override YAML, persists it as a new candidate version, and deploys
    that version."""
    from cli.commands.improve import run_improve_accept_in_process

    # Seed scratch override on disk.
    override = tmp_path / "scratch" / "accept_att1.yaml"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("system_prompt: EDITED\n", encoding="utf-8")

    # Track what deploy_invoker receives.
    deploy_calls: list[dict[str, Any]] = []

    def fake_deploy(**kw: Any) -> None:
        deploy_calls.append(kw)

    # Fake attempt + lineage.
    class _FakeAttempt:
        attempt_id = "att1"
        status = "accepted"

    class _View1:
        deployment_id = None
        deployed_version = None

    class _View2:
        deployment_id = "dep_1"
        deployed_version = 99

    # Fake version manager that records save_version calls and returns an
    # incrementing new version number.
    saved: list[tuple[dict, str]] = []

    class _FakeCV:
        def __init__(self) -> None:
            self.version = 99

    class _FakeVM:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def save_version(
            self, config: dict, scores: dict, status: str = "canary",
        ) -> Any:
            saved.append((config, status))
            return _FakeCV()

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[_FakeAttempt()],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin, \
         patch("deployer.versioning.ConfigVersionManager", _FakeVM):
        lin.return_value.view_attempt.side_effect = [_View1(), _View2()]
        lin.return_value.record_measurement.return_value = None

        result = run_improve_accept_in_process(
            attempt_id="att1",
            strategy="canary",
            on_event=lambda _e: None,
            deploy_invoker=fake_deploy,
            candidate_override_path=override,
        )

    # The override YAML was snapshotted as a new candidate version.
    assert saved, "override path should be saved as new candidate version"
    assert saved[0][0] == {"system_prompt": "EDITED"}
    assert saved[0][1] == "candidate"
    # Deploy was invoked with the new version number.
    assert len(deploy_calls) == 1
    assert deploy_calls[0]["config_version"] == 99
    assert deploy_calls[0]["attempt_id"] == "att1"
    assert result.status == "ok"


def test_run_improve_accept_without_override_uses_existing_version(
    tmp_path: Path,
) -> None:
    """Without ``candidate_override_path``, behavior is unchanged —
    deploy uses the version resolved from change_card / attempt
    metadata."""
    from cli.commands.improve import run_improve_accept_in_process

    class _FakeAttempt:
        attempt_id = "att1"
        status = "accepted"

    class _View1:
        deployment_id = None
        deployed_version = None

    class _View2:
        deployment_id = "dep_1"
        deployed_version = 5

    deploy_calls: list[dict[str, Any]] = []

    def fake_deploy(**kw: Any) -> None:
        deploy_calls.append(kw)

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[_FakeAttempt()],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin, \
         patch(
             "cli.commands.improve._resolve_attempt_candidate_version",
             return_value=7,
         ):
        lin.return_value.view_attempt.side_effect = [_View1(), _View2()]
        lin.return_value.record_measurement.return_value = None

        run_improve_accept_in_process(
            attempt_id="att1",
            strategy="canary",
            on_event=lambda _e: None,
            deploy_invoker=fake_deploy,
            # candidate_override_path intentionally omitted — legacy.
        )

    assert len(deploy_calls) == 1
    assert deploy_calls[0]["config_version"] == 7


# ---------------------------------------------------------------------------
# Slash handler --edit flow
# ---------------------------------------------------------------------------


ORIGINAL_YAML = "system_prompt: original\nmodel: gpt-4\n"
EDITED_YAML = "system_prompt: EDITED\nmodel: gpt-4\n"


def test_accept_without_edit_flag_keeps_legacy_path(
    ctx: SlashContext, echo: _EchoCapture, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test A: no ``--edit`` → accept is invoked via the normal streaming
    runner; no override kwarg leaks through; no scratch file is written."""
    runner = _fake_runner(
        [{"event": "improve_accept_complete", "attempt_id": "att_abc", "status": "ok"}]
    )
    _install_improve(ctx, runner)

    # Pre-populate session so the attempt_id resolves.
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_abc")
    ctx.meta["workbench_session"] = session

    dispatch(ctx, "/improve accept att_abc")

    # Normal streaming runner invoked with [sub, attempt_id] — no override.
    assert runner.calls == [["accept", "att_abc"]]
    # No scratch dir created.
    scratch = tmp_path / ".agentlab" / "scratch"
    assert not scratch.exists()


def test_accept_with_edit_writes_scratch_and_passes_override(
    ctx: SlashContext, echo: _EchoCapture, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test B (core): --edit → seam returns edited YAML → scratch file
    written → ``run_improve_accept_in_process`` is called directly with
    ``candidate_override_path`` set to the scratch path."""
    candidate = _seed_candidate_yaml(tmp_path, ORIGINAL_YAML)
    _install_lineage_view(ctx, "att_abc", candidate)

    runner = _fake_runner([])  # streaming runner is NOT used for the edit branch
    _install_improve(ctx, runner)

    # Monkeypatch the seam to return the "edited" YAML.
    monkeypatch.setattr(
        improve_slash, "_prompt_yaml_edit", lambda _original: EDITED_YAML,
    )

    # Record the accept call.
    accept_calls: list[dict[str, Any]] = []

    def _fake_accept(**kw: Any) -> Any:
        accept_calls.append(kw)
        on_event = kw.get("on_event")
        if on_event is not None:
            on_event({
                "event": "improve_accept_complete",
                "attempt_id": "att_abc",
                "status": "ok",
            })

        class _R:
            status = "ok"
            attempt_id = "att_abc"
            deployment_id = "dep_1"

        return _R()

    monkeypatch.setattr(
        improve_slash, "run_improve_accept_in_process", _fake_accept,
        raising=False,
    )

    dispatch(ctx, "/improve accept att_abc --edit")

    # Streaming runner was bypassed.
    assert runner.calls == []

    # Scratch file written to <workspace>/.agentlab/scratch/accept_<id>.yaml.
    scratch = tmp_path / ".agentlab" / "scratch" / "accept_att_abc.yaml"
    assert scratch.exists(), f"expected scratch file at {scratch}"
    assert scratch.read_text(encoding="utf-8") == EDITED_YAML

    # Accept was invoked with candidate_override_path pointing at the scratch.
    assert len(accept_calls) == 1
    assert accept_calls[0]["attempt_id"] == "att_abc"
    assert Path(accept_calls[0]["candidate_override_path"]) == scratch


def test_accept_edit_cancel_path_skips_accept(
    ctx: SlashContext, echo: _EchoCapture, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test C: seam returns None → cancelled markup, no accept, no scratch."""
    candidate = _seed_candidate_yaml(tmp_path, ORIGINAL_YAML)
    _install_lineage_view(ctx, "att_abc", candidate)

    runner = _fake_runner([])
    _install_improve(ctx, runner)

    monkeypatch.setattr(improve_slash, "_prompt_yaml_edit", lambda _o: None)

    accept_calls: list[dict[str, Any]] = []

    def _fake_accept(**kw: Any) -> Any:
        accept_calls.append(kw)

    monkeypatch.setattr(
        improve_slash, "run_improve_accept_in_process", _fake_accept,
        raising=False,
    )

    dispatch(ctx, "/improve accept att_abc --edit")

    assert accept_calls == []
    # No scratch file created on cancel.
    scratch = tmp_path / ".agentlab" / "scratch" / "accept_att_abc.yaml"
    assert not scratch.exists()
    # Cancelled markup emitted.
    plain = "\n".join(echo.lines)
    assert "edit cancelled" in plain.lower()


def test_accept_edit_unknown_attempt(
    ctx: SlashContext, echo: _EchoCapture, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test D: unknown attempt → error markup, no accept call."""
    _install_unknown_attempt_store(ctx)

    runner = _fake_runner([])
    _install_improve(ctx, runner)

    accept_calls: list[dict[str, Any]] = []

    def _fake_accept(**kw: Any) -> Any:
        accept_calls.append(kw)

    monkeypatch.setattr(
        improve_slash, "run_improve_accept_in_process", _fake_accept,
        raising=False,
    )
    # Seam should never be reached, but stub anyway.
    monkeypatch.setattr(
        improve_slash, "_prompt_yaml_edit", lambda _o: EDITED_YAML,
    )

    dispatch(ctx, "/improve accept att_missing --edit")

    assert accept_calls == []
    plain = "\n".join(echo.lines)
    assert "unknown attempt" in plain.lower()
