"""Tests for CoverageAnalyzer.gap_signal() and gap_signal_dict() (R3.1)."""

from evals.coverage_analyzer import (
    CoverageAnalyzer,
    CoverageGap,
    CoverageReport,
)


def _gap(surface: str, severity: str, current: int, recommended: int) -> CoverageGap:
    return CoverageGap(
        surface=surface,
        component_name=f"{surface}_component",
        gap_type="low_coverage",
        current_count=current,
        recommended_count=recommended,
        description=f"{surface} has {current}/{recommended} cases",
        severity=severity,
    )


def _analyzer_with_report(gaps: list[CoverageGap]) -> CoverageAnalyzer:
    report = CoverageReport(total_cases=0, gaps=gaps)
    analyzer = CoverageAnalyzer()
    analyzer._last_report = report
    return analyzer


def test_gap_signal_returns_sorted_tuples() -> None:
    analyzer = _analyzer_with_report([
        _gap("api", "high", 2, 10),       # delta=8
        _gap("cli", "low", 1, 3),         # delta=2
        _gap("db", "high", 0, 5),         # delta=5
        _gap("auth", "critical", 0, 4),   # delta=4
        _gap("ui", "medium", 1, 4),       # delta=3
    ])
    signal = analyzer.gap_signal()
    # Sorted: severity desc (critical > high > medium > low), then delta desc
    assert signal[0] == ("auth", "critical", 4)
    # Both "high" entries come next, larger delta first
    assert signal[1] == ("api", "high", 8)
    assert signal[2] == ("db", "high", 5)
    assert signal[3] == ("ui", "medium", 3)
    assert signal[4] == ("cli", "low", 2)


def test_gap_signal_empty_when_no_report() -> None:
    analyzer = CoverageAnalyzer()
    assert analyzer.gap_signal() == []
    assert analyzer.gap_signal_dict() == {}


def test_gap_signal_dict_keys_surfaces() -> None:
    analyzer = _analyzer_with_report([
        _gap("api", "high", 0, 10),
        _gap("cli", "low", 1, 3),
    ])
    d = analyzer.gap_signal_dict()
    assert set(d.keys()) == {"api", "cli"}
    assert d["api"]["gap"] == 10
    assert d["api"]["severity"] == "high"
    assert d["api"]["current"] == 0
    assert d["api"]["recommended"] == 10
    assert "description" in d["api"]


def test_gap_signal_dict_aggregates_same_surface() -> None:
    """When multiple gaps share a surface, aggregate to max severity and max delta.

    The real analyzer emits one gap per route/tool/guardrail/category, all sharing
    the same `surface` string (e.g., "routing_rule", "guardrail", "category"). The
    dict keys by surface, so duplicates must aggregate rather than collapse to last.
    """
    analyzer = _analyzer_with_report([
        _gap("routing_rule", "high", 1, 2),       # delta=1
        _gap("routing_rule", "critical", 0, 5),   # delta=5, higher severity
        _gap("routing_rule", "medium", 0, 10),    # delta=10, but lower severity
    ])
    d = analyzer.gap_signal_dict()
    assert set(d.keys()) == {"routing_rule"}
    # Aggregated: highest severity wins, and largest delta tracked independently
    assert d["routing_rule"]["severity"] == "critical"
    assert d["routing_rule"]["gap"] == 10  # max delta across entries


def test_analyze_caches_last_report() -> None:
    """analyze() should cache its result for later gap_signal() calls."""
    # Use a minimal mock card: no routes/tools/guardrails/sub-agents.
    class _MockCard:
        routing_rules: list = []
        guardrails: list = []
        sub_agents: list = []

        def all_tool_names(self) -> list[str]:
            return []

    analyzer = CoverageAnalyzer()
    assert analyzer._last_report is None
    report = analyzer.analyze(_MockCard(), existing_cases=[])
    assert analyzer._last_report is report
