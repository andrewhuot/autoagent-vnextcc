from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOAGENT_DIR = REPO_ROOT / ".autoagent"


def _wait_for_port(port: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"Port {port} did not open within {timeout_seconds} seconds")


def _get_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _preserved_pid_files() -> None:
    AUTOAGENT_DIR.mkdir(exist_ok=True)
    backups: list[tuple[Path, Path]] = []

    try:
        for name in ("backend.pid", "frontend.pid"):
            path = AUTOAGENT_DIR / name
            backup = AUTOAGENT_DIR / f"{name}.bak-test"
            if path.exists():
                shutil.move(path, backup)
                backups.append((path, backup))
        yield
    finally:
        for name in ("backend.pid", "frontend.pid"):
            path = AUTOAGENT_DIR / name
            if path.exists():
                path.unlink()
        for path, backup in backups:
            if backup.exists():
                shutil.move(backup, path)


@contextmanager
def _fake_lsof(pid_by_port: dict[int, int]) -> None:
    with tempfile.TemporaryDirectory() as bindir:
        script = Path(bindir) / "lsof"
        lines = ["#!/bin/sh"]
        for port, pid in pid_by_port.items():
            lines.extend(
                [
                    f'if [ "$1" = "-ti" ] && [ "$2" = ":{port}" ]; then',
                    f"  echo {pid}",
                    "fi",
                ]
            )
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bindir}:{env['PATH']}"
        yield env


@contextmanager
def _path_without_lsof(*, fake_npm_body: str | None = None) -> None:
    """Provide a PATH with the minimum commands needed by start.sh, but no lsof."""

    required_commands = [
        "awk",
        "cat",
        "curl",
        "cut",
        "dirname",
        "mkdir",
        "ps",
        "python3",
        "rm",
        "sed",
        "sleep",
        "tail",
    ]

    with tempfile.TemporaryDirectory() as bindir:
        bin_path = Path(bindir)

        for name in required_commands:
            source = shutil.which(name)
            if source is None:
                raise AssertionError(f"Required command not found for test: {name}")
            (bin_path / name).symlink_to(source)

        npm_script = bin_path / "npm"
        if fake_npm_body is None:
            source = shutil.which("npm")
            if source is None:
                raise AssertionError("Required command not found for test: npm")
            npm_script.symlink_to(source)
        else:
            npm_script.write_text(f"#!/bin/sh\n{fake_npm_body}\n", encoding="utf-8")
            npm_script.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = str(bin_path)
        yield env


def test_stop_script_does_not_kill_unrelated_processes() -> None:
    with _preserved_pid_files():
        occupant = subprocess.Popen(
            [sys.executable, "-m", "http.server", "8000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_port(8000)
            with _fake_lsof({8000: occupant.pid}) as env:
                result = subprocess.run(
                    ["/bin/bash", str(REPO_ROOT / "stop.sh")],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                    timeout=20,
                )

            assert result.returncode == 0
            assert occupant.poll() is None
        finally:
            if occupant.poll() is None:
                occupant.terminate()
                occupant.wait(timeout=5)


def test_start_script_refuses_occupied_ports_without_killing_other_processes() -> None:
    with _preserved_pid_files():
        occupant = subprocess.Popen(
            [sys.executable, "-m", "http.server", "8000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_port(8000)
            with _fake_lsof({8000: occupant.pid}) as env:
                result = subprocess.run(
                    ["/bin/bash", str(REPO_ROOT / "start.sh")],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                    timeout=20,
                )

            combined_output = f"{result.stdout}\n{result.stderr}"
            assert result.returncode == 1
            assert occupant.poll() is None
            assert "port 8000" in combined_output.lower()
        finally:
            if occupant.poll() is None:
                occupant.terminate()
                occupant.wait(timeout=5)


def test_start_script_refuses_frontend_port_conflicts_without_lsof() -> None:
    """start.sh should still block occupied frontend ports when lsof is unavailable."""

    with _preserved_pid_files():
        occupant = subprocess.Popen(
            [sys.executable, "-m", "http.server", "5173"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_port(5173)
            with _path_without_lsof(fake_npm_body="exit 0") as env:
                env["BACKEND_PORT"] = str(_get_free_port())
                result = subprocess.run(
                    ["/bin/bash", str(REPO_ROOT / "start.sh")],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                    timeout=20,
                )

            combined_output = f"{result.stdout}\n{result.stderr}".lower()
            assert result.returncode == 1
            assert occupant.poll() is None
            assert "frontend port 5173" in combined_output
        finally:
            if occupant.poll() is None:
                occupant.terminate()
                occupant.wait(timeout=5)
