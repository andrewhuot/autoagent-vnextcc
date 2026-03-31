from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PATH = "/bin:/usr/bin:/usr/sbin:/sbin"


def _write_fake_python(bindir: Path, name: str, version: str) -> None:
    script = bindir / name
    script.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "-c" ]; then',
                f"  printf '%s\\n' '{version}'",
                "  exit 0",
                "fi",
                'printf \'unexpected args for %s: %s\\n\' \"$0\" \"$*\" >&2',
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


def _run_setup_command(command: str, bindir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AUTOAGENT_SETUP_SOURCE_ONLY"] = "1"
    env["PATH"] = f"{bindir}:{SYSTEM_PATH}"
    return subprocess.run(
        ["/bin/bash", "-c", f'source "{REPO_ROOT / "setup.sh"}"; {command}'],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_setup_script_prefers_python312_over_other_compatible_commands() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        bindir = Path(tmpdir)
        _write_fake_python(bindir, "python3.12", "3.12")
        _write_fake_python(bindir, "python3.13", "3.13")
        _write_fake_python(bindir, "python3.14", "3.14")
        _write_fake_python(bindir, "python3.11", "3.11")
        _write_fake_python(bindir, "python3", "3.14")

        result = _run_setup_command("find_compatible_python", bindir)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "python3.12"


def test_setup_script_uses_python311_before_falling_back_to_python3() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        bindir = Path(tmpdir)
        _write_fake_python(bindir, "python3.12", "3.10")
        _write_fake_python(bindir, "python3.13", "3.10")
        _write_fake_python(bindir, "python3.14", "3.10")
        _write_fake_python(bindir, "python3.11", "3.11")
        _write_fake_python(bindir, "python3", "3.14")

        result = _run_setup_command("find_compatible_python", bindir)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "python3.11"


def test_setup_script_falls_back_to_python3_when_it_is_the_only_supported_option() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        bindir = Path(tmpdir)
        _write_fake_python(bindir, "python3.12", "3.10")
        _write_fake_python(bindir, "python3.13", "3.10")
        _write_fake_python(bindir, "python3.14", "3.10")
        _write_fake_python(bindir, "python3.11", "3.10")
        _write_fake_python(bindir, "python3", "3.11")

        result = _run_setup_command("find_compatible_python", bindir)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "python3"


def test_setup_script_reports_homebrew_install_instructions_when_no_supported_python_exists() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        bindir = Path(tmpdir)
        # Shadow ALL candidate names so real system pythons don't leak through PATH
        for name in ("python3.12", "python3.13", "python3.14", "python3.11", "python3"):
            _write_fake_python(bindir, name, "3.9")

        result = _run_setup_command("select_compatible_python_or_die", bindir)

    combined_output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 1
    assert "Python 3.11+ is required" in combined_output
    assert "brew install python@3.12" in combined_output
    assert "python3.12, python3.13, python3.14, python3.11, python3" in combined_output
