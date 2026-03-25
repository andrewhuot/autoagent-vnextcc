"""Enforce dependency layer boundaries.

Layer 0 (core loop) must not import from Layer 1 (advanced) or Layer 2 (surface).
Layer 1 (advanced) must not import from Layer 2 (surface).

See DEPENDENCY_LAYERS.md for the full spec.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Layer definitions — map each module prefix to its layer number
# ---------------------------------------------------------------------------

LAYER_0_PREFIXES = {
    "core",
    "agent.config",
    "evals.scorer",
    "evals.scorer_spec",
    "evals.runner",
    "evals.statistics",
    "evals.data_engine",
    "evals.fixtures",
    "evals.history",
    "evals.replay",
    "evals.side_effects",
    "evals.synthetic",
    "optimizer.loop",
    "optimizer.proposer",
    "optimizer.mutations",
    "optimizer.mutations_google",
    "optimizer.mutations_topology",
    "optimizer.experiments",
    "optimizer.gates",
    "optimizer.search",
    "optimizer.bandit",
    "optimizer.providers",
    "optimizer.memory",
    "optimizer.cost_tracker",
    "optimizer.reliability",
    "optimizer.human_control",
    "observer.metrics",
    "observer.classifier",
    "observer.traces",
    "observer.opportunities",
    "evals.anti_goodhart",
    "logger",
    "data",
}

LAYER_1_PREFIXES = {
    "optimizer.prompt_opt",
    "optimizer.change_card",
    "optimizer.diff_engine",
    "optimizer.sandbox",
    "optimizer.mode_router",
    "optimizer.model_routing",
    "optimizer.autofix",
    "optimizer.autofix_proposers",
    "optimizer.autofix_vertex",
    "optimizer.curriculum",
    "optimizer.pareto",
    "optimizer.holdout",
    "optimizer.training_escalation",
    "observer.trace_grading",
    "observer.blame_map",
    "observer.trace_graph",
    "observer.anomaly",
    "context",
    "judges",
    "graders",
    "evals.nl_compiler",
    "evals.nl_scorer",
    "evals.anti_goodhart",
    "registry",
    "deployer",
    "control",
}

LAYER_2_PREFIXES = {
    "api",
    "web",
    "agent.server",
    "agent.dashboard_data",
}

# runner.py is special — it's the CLI and can import anything
EXEMPT = {"runner", "tests", "conftest"}


def _get_layer(module: str) -> int | None:
    """Return 0, 1, or 2 for the module's layer, or None if exempt/external."""
    for prefix in EXEMPT:
        if module.startswith(prefix):
            return None
    for prefix in sorted(LAYER_0_PREFIXES, key=len, reverse=True):
        if module == prefix or module.startswith(prefix + "."):
            return 0
    for prefix in sorted(LAYER_1_PREFIXES, key=len, reverse=True):
        if module == prefix or module.startswith(prefix + "."):
            return 1
    for prefix in sorted(LAYER_2_PREFIXES, key=len, reverse=True):
        if module == prefix or module.startswith(prefix + "."):
            return 2
    return None  # external package


def _extract_imports(filepath: Path) -> list[str]:
    """Extract all imported module names from a Python file."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute imports only
                imports.append(node.module)
    return imports


def _module_name_from_path(filepath: Path) -> str:
    """Convert file path to dotted module name."""
    rel = filepath.relative_to(ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def _collect_violations() -> list[tuple[str, str, int, int]]:
    """Find all layer boundary violations.

    Returns list of (source_module, imported_module, source_layer, imported_layer).
    """
    violations = []
    for dirpath, _, filenames in os.walk(ROOT):
        # Skip non-source dirs
        rel = Path(dirpath).relative_to(ROOT)
        if any(
            part.startswith(".")
            or part in {"__pycache__", "node_modules", "web", ".git", "venv", ".venv"}
            for part in rel.parts
        ):
            continue

        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            filepath = Path(dirpath) / fname
            source_module = _module_name_from_path(filepath)
            source_layer = _get_layer(source_module)
            if source_layer is None:
                continue

            for imported in _extract_imports(filepath):
                imported_layer = _get_layer(imported)
                if imported_layer is None:
                    continue
                if imported_layer > source_layer:
                    violations.append(
                        (source_module, imported, source_layer, imported_layer)
                    )
    return violations


class TestDependencyLayers:
    """Verify that layer boundaries are respected."""

    def test_layer_0_does_not_import_layer_1(self):
        violations = [
            (src, imp, sl, il)
            for src, imp, sl, il in _collect_violations()
            if sl == 0 and il == 1
        ]
        if violations:
            msg = "Layer 0 (core) imports from Layer 1 (advanced):\n"
            for src, imp, _, _ in violations:
                msg += f"  {src} → {imp}\n"
            pytest.fail(msg)

    def test_layer_0_does_not_import_layer_2(self):
        violations = [
            (src, imp, sl, il)
            for src, imp, sl, il in _collect_violations()
            if sl == 0 and il == 2
        ]
        if violations:
            msg = "Layer 0 (core) imports from Layer 2 (surface):\n"
            for src, imp, _, _ in violations:
                msg += f"  {src} → {imp}\n"
            pytest.fail(msg)

    def test_layer_1_does_not_import_layer_2(self):
        violations = [
            (src, imp, sl, il)
            for src, imp, sl, il in _collect_violations()
            if sl == 1 and il == 2
        ]
        if violations:
            msg = "Layer 1 (advanced) imports from Layer 2 (surface):\n"
            for src, imp, _, _ in violations:
                msg += f"  {src} → {imp}\n"
            pytest.fail(msg)

    def test_no_violations_summary(self):
        """Single summary test that catches any boundary violation."""
        violations = _collect_violations()
        if violations:
            msg = f"{len(violations)} layer boundary violation(s):\n"
            layer_names = {0: "core", 1: "advanced", 2: "surface"}
            for src, imp, sl, il in violations:
                msg += f"  [{layer_names[sl]}] {src} → [{layer_names[il]}] {imp}\n"
            pytest.fail(msg)
