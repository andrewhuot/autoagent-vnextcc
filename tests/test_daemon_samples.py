"""Validation for C12 daemon samples + docs.

Covers:
- File existence for contrib/systemd/agentlab-loop.service,
  contrib/launchd/com.agentlab.loop.plist,
  docs/continuous-mode.md,
  and the R4 widgets section in docs/workbench-quickstart.md.
- systemd unit parses as INI and has the expected sections / ExecStart.
- launchd plist parses via plistlib with the expected keys and values.
- Docs smoke test: required topics are mentioned.
- If `systemd-analyze` is on PATH, it is invoked as an extra lint
  (skipped on hosts without it, e.g. macOS CI).
"""
from __future__ import annotations

import configparser
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEMD_UNIT = REPO_ROOT / "contrib" / "systemd" / "agentlab-loop.service"
LAUNCHD_PLIST = REPO_ROOT / "contrib" / "launchd" / "com.agentlab.loop.plist"
DOC_CONTINUOUS = REPO_ROOT / "docs" / "continuous-mode.md"
DOC_WORKBENCH = REPO_ROOT / "docs" / "workbench-quickstart.md"


# --- File existence --------------------------------------------------------


def test_systemd_unit_exists() -> None:
    assert SYSTEMD_UNIT.is_file(), f"missing {SYSTEMD_UNIT}"


def test_launchd_plist_exists() -> None:
    assert LAUNCHD_PLIST.is_file(), f"missing {LAUNCHD_PLIST}"


def test_continuous_mode_doc_exists() -> None:
    assert DOC_CONTINUOUS.is_file(), f"missing {DOC_CONTINUOUS}"


def test_workbench_quickstart_has_r4_widgets_section() -> None:
    assert DOC_WORKBENCH.is_file(), f"missing {DOC_WORKBENCH}"
    text = DOC_WORKBENCH.read_text(encoding="utf-8")
    # Exact section header from the task contract.
    assert "R4 Workbench widgets" in text, (
        "workbench-quickstart.md must include the 'R4 Workbench widgets' section"
    )


# --- systemd validation ----------------------------------------------------


def test_systemd_unit_parses_as_ini_with_expected_sections() -> None:
    parser = configparser.ConfigParser(
        allow_no_value=True, interpolation=None, strict=False
    )
    # configparser does not accept duplicate keys by default — the unit
    # file does not have any, but strict=False keeps us forward-compatible.
    parser.read(SYSTEMD_UNIT, encoding="utf-8")

    for section in ("Unit", "Service", "Install"):
        assert parser.has_section(section), f"missing [{section}] section"

    exec_start = parser.get("Service", "ExecStart")
    assert "agentlab loop run --schedule continuous" in exec_start, (
        f"ExecStart must invoke `agentlab loop run --schedule continuous`, got: "
        f"{exec_start!r}"
    )


def test_systemd_analyze_verify_if_available(tmp_path: Path) -> None:
    """Run `systemd-analyze verify` when present; skip otherwise.

    systemd-analyze is not available on macOS CI hosts; this test is a
    best-effort lint that kicks in on Linux dev machines.
    """
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze not available on this host")

    # systemd-analyze verify expects the file basename to end in a unit
    # suffix (.service / .target / etc.), which ours does.
    result = subprocess.run(
        ["systemd-analyze", "verify", str(SYSTEMD_UNIT)],
        capture_output=True,
        text=True,
        check=False,
    )
    # systemd-analyze exits non-zero on hard errors; warnings are written
    # to stderr but exit 0. We treat any non-zero as a failure and surface
    # stderr for the diff.
    assert result.returncode == 0, (
        f"systemd-analyze verify failed:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# --- launchd validation ----------------------------------------------------


def test_launchd_plist_parses_and_has_expected_keys() -> None:
    data = plistlib.loads(LAUNCHD_PLIST.read_bytes())

    assert data.get("Label") == "com.agentlab.loop"

    program_args = data.get("ProgramArguments")
    assert isinstance(program_args, list) and program_args, (
        "ProgramArguments must be a non-empty list"
    )
    joined = " ".join(program_args)
    assert "agentlab" in joined, "ProgramArguments must reference the agentlab binary"
    assert "loop" in program_args and "run" in program_args, (
        "ProgramArguments must invoke `loop run`"
    )

    keep_alive = data.get("KeepAlive")
    assert isinstance(keep_alive, dict), "KeepAlive must be a dict"
    assert keep_alive.get("SuccessfulExit") is False, (
        "KeepAlive.SuccessfulExit must be false so the daemon restarts on crash"
    )

    assert data.get("ThrottleInterval") == 30, (
        "ThrottleInterval must be 30 seconds"
    )

    env = data.get("EnvironmentVariables")
    assert isinstance(env, dict) and env.get("AGENTLAB_STRICT_LIVE") == "1", (
        "EnvironmentVariables must set AGENTLAB_STRICT_LIVE=1"
    )


# --- docs smoke ------------------------------------------------------------


def test_continuous_mode_doc_mentions_expected_topics() -> None:
    text = DOC_CONTINUOUS.read_text(encoding="utf-8").lower()
    for token in (
        "overview",
        "notification",
        "drift",
        "tradeoff",
        "strict-live",
        "troubleshoot",
    ):
        assert token in text, f"docs/continuous-mode.md missing topic: {token!r}"


def test_workbench_quickstart_mentions_r4_widget_commands() -> None:
    text = DOC_WORKBENCH.read_text(encoding="utf-8")
    for token in ("/attempt-diff", "/lineage", "--edit", "Cost:"):
        assert token in text, (
            f"docs/workbench-quickstart.md missing R4 widget reference: {token!r}"
        )
