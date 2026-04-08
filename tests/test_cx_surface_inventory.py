"""Tests for the docs-driven CX Agent Studio surface inventory."""

from __future__ import annotations

from cx_studio.surface_inventory import build_cx_surface_matrix


def test_build_cx_surface_matrix_reports_current_support_truthfully() -> None:
    """The CX matrix should expose supported, partial, read-only, and unsupported surfaces."""

    matrix = build_cx_surface_matrix()

    summary = matrix["summary"]
    surfaces = {item["surface_id"]: item for item in matrix["surfaces"]}

    assert summary["total_surfaces"] >= 15
    assert summary["support_level_counts"]["supported"] >= 3
    assert summary["support_level_counts"]["partial"] >= 2
    assert summary["support_level_counts"]["read_only"] >= 5
    assert summary["support_level_counts"]["unsupported"] >= 2

    assert surfaces["instructions"]["support_level"] == "supported"
    assert surfaces["routing"]["support_level"] == "partial"
    assert surfaces["app_tools"]["support_level"] == "read_only"
    assert surfaces["playbook_examples"]["support_level"] == "unsupported"

    assert any(
        "projects.locations.agents.playbooks" in ref for ref in surfaces["playbook_examples"]["documentation_refs"]
    )
    assert any("cx_studio/surface_inventory.py" in ref for ref in surfaces["instructions"]["code_refs"])
