"""Golden-file snapshots of `agentlab --help` output.

These tests lock the CLI's top-level and per-group help text byte-for-byte
so runner.py refactors (Slice C of R2) cannot silently drift user-visible
output. If a refactor *intentionally* changes help text, regenerate the
golden file in the same commit:

    uv run agentlab --help > tests/golden/agentlab_help.txt
    uv run agentlab improve --help > tests/golden/improve_help.txt
    ...

The subprocess is invoked with a stable environment (no AGENTLAB_* overrides,
no terminal color) so output is deterministic across machines.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


def _clean_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("AGENTLAB_")
    }
    # Click respects NO_COLOR; keep output plain.
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    env.setdefault("COLUMNS", "80")
    return env


def _run_help(args: list[str]) -> str:
    result = subprocess.run(
        ["uv", "run", "--quiet", "agentlab", *args, "--help"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )
    # Click exits 0 on --help; fail loudly if that changes.
    assert result.returncode == 0, (
        f"agentlab {' '.join(args)} --help exited {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    return result.stdout


@pytest.mark.parametrize(
    "args,fname",
    [
        ([], "agentlab_help.txt"),
        (["improve"], "improve_help.txt"),
        (["eval"], "eval_help.txt"),
        (["build"], "build_help.txt"),
        (["optimize"], "optimize_help.txt"),
        (["deploy"], "deploy_help.txt"),
    ],
    ids=["root", "improve", "eval", "build", "optimize", "deploy"],
)
def test_help_matches_golden(args: list[str], fname: str) -> None:
    golden_path = GOLDEN_DIR / fname
    assert golden_path.exists(), (
        f"Missing golden file {golden_path}. "
        f"Regenerate with: uv run agentlab {' '.join(args)} --help > {golden_path}"
    )
    expected = golden_path.read_text()
    actual = _run_help(args)
    if actual != expected:
        pytest.fail(
            f"`agentlab {' '.join(args)} --help` drifted from golden.\n"
            f"If this change is intentional, regenerate:\n"
            f"  uv run agentlab {' '.join(args)} --help > {golden_path}\n"
            f"Diff (first 40 lines):\n"
            + _unified_diff_preview(expected, actual)
        )


def _unified_diff_preview(expected: str, actual: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="golden",
        tofile="actual",
        n=2,
    )
    return "".join(list(diff)[:40])
