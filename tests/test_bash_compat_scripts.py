from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_SCRIPTS = (
    REPO_ROOT / "start.sh",
    REPO_ROOT / "setup.sh",
    REPO_ROOT / "stop.sh",
)
RISKY_UNICODE_CHARS = {
    "…": "ellipsis",
    "–": "en dash",
    "—": "em dash",
    "·": "middle dot",
}
BASH32_INCOMPATIBLE_PATTERNS = {
    "bash 4 case modification": re.compile(r"\$\{[^}]*([,]{2}|\^\^)[^}]*\}"),
    "associative array": re.compile(r"declare\s+-A\b"),
    "stderr pipe shorthand": re.compile(r"\|&"),
    "readarray/mapfile builtin": re.compile(r"\b(?:readarray|mapfile)\b"),
    "prefix indirect expansion": re.compile(r"\$\{![A-Za-z_][A-Za-z0-9_]*[@*]\}"),
}
UNBRACED_NAMED_VARIABLE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _format_failures(failures: list[str]) -> str:
    return "\n".join(failures)


@pytest.mark.parametrize("script_path", TARGET_SCRIPTS, ids=lambda path: path.name)
def test_scripts_parse_with_system_bash(script_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", "-n", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"{script_path.name} failed /bin/bash -n validation.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("script_path", TARGET_SCRIPTS, ids=lambda path: path.name)
def test_scripts_do_not_use_prompt_flagged_unicode_punctuation(script_path: Path) -> None:
    failures: list[str] = []

    for line_number, line in enumerate(_read_script(script_path).splitlines(), start=1):
        for character, label in RISKY_UNICODE_CHARS.items():
            if character in line:
                failures.append(
                    f"{script_path.name}:{line_number} contains {label}: {line}"
                )

    assert not failures, _format_failures(failures)


@pytest.mark.parametrize("script_path", TARGET_SCRIPTS, ids=lambda path: path.name)
def test_non_ascii_lines_use_braced_named_variables(script_path: Path) -> None:
    failures: list[str] = []

    for line_number, line in enumerate(_read_script(script_path).splitlines(), start=1):
        if not any(ord(character) > 127 for character in line):
            continue

        for match in UNBRACED_NAMED_VARIABLE.finditer(line):
            failures.append(
                f"{script_path.name}:{line_number} uses unbraced variable "
                f"{match.group(0)} on a non-ASCII line: {line}"
            )

    assert not failures, _format_failures(failures)


@pytest.mark.parametrize("script_path", TARGET_SCRIPTS, ids=lambda path: path.name)
def test_scripts_do_not_use_bash32_incompatible_features(script_path: Path) -> None:
    failures: list[str] = []
    script_text = _read_script(script_path)

    for label, pattern in BASH32_INCOMPATIBLE_PATTERNS.items():
        for match in pattern.finditer(script_text):
            line_number = script_text.count("\n", 0, match.start()) + 1
            line = script_text.splitlines()[line_number - 1]
            failures.append(f"{script_path.name}:{line_number} uses {label}: {line}")

    assert not failures, _format_failures(failures)
