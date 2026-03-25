"""Unit tests for MetricLayer display names (metric relabeling)."""

from __future__ import annotations

import pytest

from core.types import METRIC_LAYER_DISPLAY_NAMES, MetricLayer


class TestMetricLayerDisplayNames:
    def test_hard_gate_display_name(self):
        assert MetricLayer.HARD_GATE.display_name == "Guardrails"

    def test_outcome_display_name(self):
        assert MetricLayer.OUTCOME.display_name == "Objectives"

    def test_slo_display_name(self):
        assert MetricLayer.SLO.display_name == "Constraints"

    def test_diagnostic_display_name(self):
        assert MetricLayer.DIAGNOSTIC.display_name == "Diagnostics"

    def test_display_names_dict_complete(self):
        """Every MetricLayer member has a display name entry."""
        for member in MetricLayer:
            assert member.name in METRIC_LAYER_DISPLAY_NAMES, (
                f"Missing display name for {member.name}"
            )
            assert member.display_name != ""
