from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_declares_explicit_package_discovery_for_editable_installs() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    package_find = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find")
    )

    assert package_find is not None
    include = package_find.get("include") or []
    assert "api" in include
    assert "api.*" in include
    assert "agent" in include
    assert "agent.*" in include
    assert "adapters" in include
    assert "adapters.*" in include
    assert "optimizer" in include
    assert "optimizer.*" in include
    assert "portability" in include
    assert "portability.*" in include
    assert "registry" in include
    assert "registry.*" in include
    assert "shared" in include
    assert "shared.*" in include
    assert "stores" in include
    assert "stores.*" in include
    assert "web" not in include
    assert "node_modules" not in include


def test_console_script_entrypoint_module_is_packaged() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject.get("project", {}).get("scripts", {})
    setuptools_config = pyproject.get("tool", {}).get("setuptools", {})

    assert scripts.get("agentlab") == "runner:cli"
    assert "runner" in (setuptools_config.get("py-modules") or [])


def test_pyproject_declares_pep_517_backend_for_editable_installs() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    build_system = pyproject.get("build-system", {})

    assert build_system.get("build-backend") == "setuptools.build_meta"
    assert "setuptools>=68.0" in (build_system.get("requires") or [])


def test_pyproject_includes_fastapi_form_upload_runtime_dependency() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject.get("project", {}).get("dependencies", [])

    assert any(dependency.startswith("python-multipart") for dependency in dependencies)
