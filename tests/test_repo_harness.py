from __future__ import annotations

import ast
import tomllib
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _makefile_text() -> str:
    return (_project_root() / "Makefile").read_text(encoding="utf-8")


def _dockerfile_text() -> str:
    return (_project_root() / "Dockerfile").read_text(encoding="utf-8")


def _copied_paths_from_dockerfile() -> set[str]:
    copied_paths: set[str] = set()
    for raw_line in _dockerfile_text().splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        if "--from=" in line:
            continue

        parts = line.split()
        sources = parts[1:-1]
        for source in sources:
            copied_paths.add(source.rstrip("/"))
    return copied_paths


def _top_level_packages_declared_for_install() -> set[str]:
    pyproject = tomllib.loads((_project_root() / "pyproject.toml").read_text(encoding="utf-8"))
    include = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )
    return {entry for entry in include if "*" not in entry}


def _top_level_packages_imported_by_api_server() -> set[str]:
    module = ast.parse((_project_root() / "api" / "server.py").read_text(encoding="utf-8"))
    imported_packages: set[str] = {"api"}

    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            top_level = node.module.split(".", 1)[0]
            imported_packages.add(top_level)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_packages.add(alias.name.split(".", 1)[0])

    return imported_packages


def test_make_test_prefers_repo_virtualenv_python() -> None:
    """`make test` should run pytest with the repo interpreter when .venv exists."""
    makefile = _makefile_text()

    assert "PYTHON ?=" in makefile
    assert ".venv/bin/python" in makefile
    assert "$(PYTHON) -m pytest $(PYTEST_ARGS)" in makefile


def test_dockerfile_copies_sources_needed_by_packaged_api_server() -> None:
    """The runtime image should include the packages the installed app can import."""
    copied_paths = _copied_paths_from_dockerfile()

    if "." in copied_paths:
        return

    packaged_api_dependencies = _top_level_packages_declared_for_install() & _top_level_packages_imported_by_api_server()
    missing = sorted(package for package in packaged_api_dependencies if package not in copied_paths)

    assert not missing, f"Dockerfile is missing packaged API dependencies: {missing}"
