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

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTLAB_DIR = REPO_ROOT / ".agentlab"
_VENV_ACTIVATE = REPO_ROOT / ".venv" / "bin" / "activate"
_PORT_OCCUPANT_CODE = textwrap.dedent(
    """
    import socket
    import sys
    import time

    port = int(sys.argv[1])
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    try:
        while True:
            time.sleep(1)
    finally:
        sock.close()
    """
)


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


def _spawn_port_occupant(port: int) -> subprocess.Popen[str]:
    """Start a tiny TCP listener so shell-script safety tests can occupy a port reliably."""
    return subprocess.Popen(
        [sys.executable, "-c", _PORT_OCCUPANT_CODE, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


@contextmanager
def _preserved_pid_files() -> None:
    AGENTLAB_DIR.mkdir(exist_ok=True)
    backups: list[tuple[Path, Path]] = []

    try:
        for name in ("backend.pid", "frontend.pid"):
            path = AGENTLAB_DIR / name
            backup = AGENTLAB_DIR / f"{name}.bak-test"
            if path.exists():
                shutil.move(path, backup)
                backups.append((path, backup))
        yield
    finally:
        for name in ("backend.pid", "frontend.pid"):
            path = AGENTLAB_DIR / name
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
        backend_port = _get_free_port()
        occupant = _spawn_port_occupant(backend_port)
        try:
            _wait_for_port(backend_port)
            with _fake_lsof({backend_port: occupant.pid}) as env:
                env["BACKEND_PORT"] = str(backend_port)
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


@pytest.mark.skipif(
    not _VENV_ACTIVATE.exists(),
    reason="start.sh requires .venv from setup.sh; skipping in bare environments",
)
def test_start_script_refuses_occupied_ports_without_killing_other_processes() -> None:
    with _preserved_pid_files():
        backend_port = _get_free_port()
        occupant = _spawn_port_occupant(backend_port)
        try:
            _wait_for_port(backend_port)
            with _fake_lsof({backend_port: occupant.pid}) as env:
                env["BACKEND_PORT"] = str(backend_port)
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
            assert f"port {backend_port}" in combined_output.lower()
        finally:
            if occupant.poll() is None:
                occupant.terminate()
                occupant.wait(timeout=5)


@pytest.mark.skipif(
    not _VENV_ACTIVATE.exists(),
    reason="start.sh requires .venv from setup.sh; skipping in bare environments",
)
def test_start_script_refuses_frontend_port_conflicts_without_lsof() -> None:
    """start.sh should still block occupied frontend ports when lsof is unavailable."""

    with _preserved_pid_files():
        frontend_port = _get_free_port()
        occupant = _spawn_port_occupant(frontend_port)
        try:
            _wait_for_port(frontend_port)
            with _path_without_lsof(fake_npm_body="exit 0") as env:
                env["BACKEND_PORT"] = str(_get_free_port())
                env["FRONTEND_PORT"] = str(frontend_port)
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
            assert f"frontend port {frontend_port}" in combined_output
        finally:
            if occupant.poll() is None:
                occupant.terminate()
                occupant.wait(timeout=5)
