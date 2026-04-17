"""B.2c — `agentlab improve measure --replay-set <dir>` plumbing.

Tests for the new optional `cases_path` kwarg on the in-process twin
and the matching `--replay-set` flag on the click command. When unset,
behavior is byte-identical to today; when set, the path is forwarded
to ``runner._build_eval_runner(cases_dir=...)``.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from runner import cli


@dataclass
class FakeAttempt:
    attempt_id: str
    status: str = "accepted"
    score_before: float | None = 0.80
    score_after: float | None = 0.85
    change_description: str = ""
    config_section: str = "prompt"
    timestamp: float = 0.0
    config_diff: str = ""
    health_context: str = "{}"


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    return memory_db, lineage_db


def _seed_deployment(lineage_db, attempt_id):
    from optimizer.improvement_lineage import ImprovementLineageStore
    s = ImprovementLineageStore(db_path=str(lineage_db))
    s.record_deployment(attempt_id=attempt_id, deployment_id="d1", version=3)


# -------------------------------------------------------------------------
# 1. Default path: no cases_path / --replay-set => helper called WITHOUT
#    cases_path (or with cases_path=None). Terminal event payload either
#    omits cases_path or has it as None.
# -------------------------------------------------------------------------


def test_improve_measure_default_replay_unchanged(isolated_stores) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4", score_before=0.80)
    captured: dict[str, Any] = {}

    class _DeployedView:
        deployment_id = "dep_1"

    def _fake_eval(**kwargs: Any) -> float:
        captured.update(kwargs)
        return 0.85

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", side_effect=_fake_eval
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        result = run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    assert result.status == "ok"
    # Helper invoked WITHOUT cases_path or with cases_path=None.
    assert captured.get("cases_path") is None
    # Terminal event omits cases_path or has None.
    terminal = events[-1]
    assert terminal["event"] == "improve_measure_complete"
    assert terminal.get("cases_path") is None


# -------------------------------------------------------------------------
# 2. With replay set: forwards cases_dir=<path> to _build_eval_runner.
# -------------------------------------------------------------------------


def test_improve_measure_with_replay_set_uses_custom_cases(
    isolated_stores, tmp_path,
) -> None:
    """Pass a directory of YAML cases. Assert ``cases_dir=<path>`` is
    forwarded to ``_build_eval_runner`` via the post-deploy eval helper.
    """
    from cli.commands.improve import run_improve_measure_in_process
    import runner as _real_runner

    # Build a minimal replay-set directory with a YAML case.
    replay_dir = tmp_path / "replay_cases"
    replay_dir.mkdir()
    (replay_dir / "dummy.yaml").write_text("id: dummy\n")

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4", score_before=0.80)
    captured_kwargs: dict[str, Any] = {}

    class _DeployedView:
        deployment_id = "dep_1"

    class _FakeEvalRunner:
        def run(self, *, config: Any) -> Any:
            class _S:
                composite = 0.91
            return _S()

    def fake_build_eval_runner(runtime, **kwargs: Any) -> Any:
        captured_kwargs.update(kwargs)
        return _FakeEvalRunner()

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch.object(
        _real_runner, "_build_eval_runner", side_effect=fake_build_eval_runner,
    ), patch.object(
        _real_runner, "load_runtime_with_mode_preference",
        return_value=object(),
    ), patch.object(
        _real_runner, "discover_workspace", return_value=None,
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        result = run_improve_measure_in_process(
            attempt_id="a1b2c3",
            cases_path=str(replay_dir),
            on_event=events.append,
        )

    assert result.status == "ok"
    assert captured_kwargs.get("cases_dir") == str(replay_dir)
    # Terminal event surfaces the replay set path.
    terminal = events[-1]
    assert terminal["event"] == "improve_measure_complete"
    assert terminal.get("cases_path") == str(replay_dir)


# -------------------------------------------------------------------------
# 3. Missing path: click exits non-zero; in-process raises.
# -------------------------------------------------------------------------


def test_improve_measure_replay_set_missing_file_exit_1(
    isolated_stores, tmp_path,
) -> None:
    from cli.commands.improve import (
        ImproveCommandError, run_improve_measure_in_process,
    )

    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")
    missing = tmp_path / "does_not_exist"

    # Click command path.
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ):
        r = CliRunner().invoke(
            cli,
            ["improve", "measure", "a1b2c3d4", "--replay-set", str(missing)],
        )
    assert r.exit_code != 0
    out = (r.output + (r.stderr_bytes or b"").decode()).lower()
    assert "replay set" in out or "not found" in out

    # In-process path raises ImproveCommandError.
    fake = FakeAttempt("a1b2c3d4", score_before=0.80)

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.return_value = _DeployedView()
        with pytest.raises(ImproveCommandError):
            run_improve_measure_in_process(
                attempt_id="a1b2c3",
                cases_path=str(missing),
                on_event=events.append,
            )


# -------------------------------------------------------------------------
# 4. Single-file replay set rejected (only directories supported for now).
# -------------------------------------------------------------------------


def test_improve_measure_replay_set_rejects_single_file(
    isolated_stores, tmp_path,
) -> None:
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")
    single = tmp_path / "one_case.txt"
    single.write_text("hello")

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ):
        r = CliRunner().invoke(
            cli,
            ["improve", "measure", "a1b2c3d4", "--replay-set", str(single)],
        )
    assert r.exit_code != 0
    out = (r.output + (r.stderr_bytes or b"").decode()).lower()
    assert (
        "directory" in out or "unsupported" in out or "not found" in out
    )


# -------------------------------------------------------------------------
# 5. JSON envelope includes replay_set when --replay-set is set;
#    absent when not set.
# -------------------------------------------------------------------------


def test_improve_measure_json_envelope_includes_replay_set(
    isolated_stores, tmp_path,
) -> None:
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")

    replay_dir = tmp_path / "replay_cases"
    replay_dir.mkdir()
    (replay_dir / "case.yaml").write_text("id: dummy\n")

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4", score_before=0.80)],
    ), patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.86,
    ):
        r = CliRunner().invoke(cli, [
            "improve", "measure", "a1b2c3d4",
            "--json", "--replay-set", str(replay_dir),
        ])
    assert r.exit_code == 0, r.output
    payload = _json.loads(r.output.strip().split("\n")[-1])
    assert payload["status"] == "ok"
    assert payload["replay_set"] == str(replay_dir)

    # Without --replay-set the key is absent (matches measure_id pattern
    # of omitting None values from the envelope).
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4", score_before=0.80)],
    ), patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.86,
    ):
        r2 = CliRunner().invoke(cli, [
            "improve", "measure", "a1b2c3d4", "--json",
        ])
    assert r2.exit_code == 0, r2.output
    payload2 = _json.loads(r2.output.strip().split("\n")[-1])
    assert "replay_set" not in payload2
