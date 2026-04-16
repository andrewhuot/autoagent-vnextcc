"""Eval coverage analysis: identify gaps and recommend new test cases.

Compares an Agent Card's surfaces (routing rules, tools, guardrails,
sub-agents) against existing test cases to find under-tested areas.
Can auto-generate cases to fill gaps using the card case generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CoverageGap:
    """A specific gap in eval coverage."""

    surface: str  # "routing_rule", "tool", "guardrail", "sub_agent", "category"
    component_name: str  # "orders", "faq_lookup", "safety_filter", etc.
    gap_type: str  # "no_cases", "low_coverage", "no_adversarial", "no_failure_type"
    current_count: int
    recommended_count: int
    description: str
    severity: str  # "critical", "high", "medium", "low"


@dataclass
class CoverageReport:
    """Full coverage analysis report."""

    total_cases: int
    gaps: list[CoverageGap] = field(default_factory=list)
    coverage_by_surface: dict[str, float] = field(default_factory=dict)
    coverage_by_category: dict[str, int] = field(default_factory=dict)
    overall_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    @property
    def critical_gaps(self) -> list[CoverageGap]:
        return [g for g in self.gaps if g.severity == "critical"]

    @property
    def high_gaps(self) -> list[CoverageGap]:
        return [g for g in self.gaps if g.severity == "high"]

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Coverage Score: {self.overall_score:.0%}",
            f"Total Cases: {self.total_cases}",
            f"Gaps Found: {len(self.gaps)} ({len(self.critical_gaps)} critical, {len(self.high_gaps)} high)",
        ]
        if self.coverage_by_surface:
            lines.append("Surface Coverage:")
            for surface, score in sorted(self.coverage_by_surface.items()):
                bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
                lines.append(f"  {surface:<20s} {bar} {score:.0%}")
        if self.recommendations:
            lines.append("Recommendations:")
            for rec in self.recommendations[:5]:
                lines.append(f"  - {rec}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standard categories every agent should have cases for
# ---------------------------------------------------------------------------

_REQUIRED_CATEGORIES = {
    "routing": 3,     # min cases for routing correctness
    "safety": 3,      # min safety/adversarial cases
    "tool_usage": 2,  # min tool invocation cases
    "happy_path": 2,  # min positive behavior cases
    "edge_cases": 2,  # min edge case coverage
}

# Failure types that should be exercised
_FAILURE_TYPES = [
    "routing_error",
    "tool_failure",
    "safety_violation",
    "unhelpful_response",
]

# Minimum recommended cases per routing target
_MIN_CASES_PER_ROUTE = 2

# Minimum recommended cases per tool
_MIN_CASES_PER_TOOL = 1

# Minimum safety cases
_MIN_SAFETY_CASES = 3


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class CoverageAnalyzer:
    """Analyze eval test case coverage against an Agent Card."""

    def analyze(
        self,
        card: Any,  # AgentCardModel
        existing_cases: list[dict[str, Any]],
    ) -> CoverageReport:
        """Analyze coverage gaps.

        Args:
            card: An AgentCardModel describing the agent.
            existing_cases: List of test case dicts with keys like
                'id', 'category', 'user_message', 'expected_specialist',
                'expected_tool', 'safety_probe', 'expected_behavior'.

        Returns:
            A CoverageReport with gaps and recommendations.
        """
        gaps: list[CoverageGap] = []
        coverage_by_surface: dict[str, float] = {}
        coverage_by_category: dict[str, int] = {}
        recommendations: list[str] = []

        # Index existing cases
        cases_by_specialist: dict[str, list[dict]] = {}
        cases_by_tool: dict[str, list[dict]] = {}
        cases_by_category: dict[str, list[dict]] = {}
        safety_cases: list[dict] = []

        for case in existing_cases:
            specialist = case.get("expected_specialist", "")
            tool = case.get("expected_tool", "")
            category = case.get("category", "")
            is_safety = case.get("safety_probe", False) or case.get("expected_behavior") == "refuse"

            if specialist:
                cases_by_specialist.setdefault(specialist, []).append(case)
            if tool:
                cases_by_tool.setdefault(tool, []).append(case)
            if category:
                cases_by_category.setdefault(category, []).append(case)
                coverage_by_category[category] = coverage_by_category.get(category, 0) + 1
            if is_safety:
                safety_cases.append(case)

        # 1. Routing coverage
        routing_gaps = self._analyze_routing(card, cases_by_specialist)
        gaps.extend(routing_gaps)
        route_targets = [r.target for r in getattr(card, "routing_rules", [])]
        if route_targets:
            covered = sum(1 for t in route_targets if len(cases_by_specialist.get(t, [])) >= _MIN_CASES_PER_ROUTE)
            coverage_by_surface["routing"] = covered / len(route_targets)
        else:
            coverage_by_surface["routing"] = 1.0  # no routes = nothing to test

        # 2. Tool coverage
        tool_gaps = self._analyze_tools(card, cases_by_tool)
        gaps.extend(tool_gaps)
        all_tools = getattr(card, "all_tool_names", lambda: [])()
        if all_tools:
            covered = sum(1 for t in all_tools if len(cases_by_tool.get(t, [])) >= _MIN_CASES_PER_TOOL)
            coverage_by_surface["tools"] = covered / len(all_tools)
        else:
            coverage_by_surface["tools"] = 1.0

        # 3. Safety coverage
        safety_gaps = self._analyze_safety(card, safety_cases)
        gaps.extend(safety_gaps)
        guardrails = getattr(card, "guardrails", [])
        guardrail_count = max(len(guardrails), 1)
        coverage_by_surface["safety"] = min(1.0, len(safety_cases) / max(_MIN_SAFETY_CASES, guardrail_count))

        # 4. Sub-agent coverage
        sub_agent_gaps = self._analyze_sub_agents(card, cases_by_specialist)
        gaps.extend(sub_agent_gaps)
        sub_agents = getattr(card, "sub_agents", [])
        if sub_agents:
            covered = sum(1 for sa in sub_agents if len(cases_by_specialist.get(sa.name, [])) > 0)
            coverage_by_surface["sub_agents"] = covered / len(sub_agents)
        else:
            coverage_by_surface["sub_agents"] = 1.0

        # 5. Category balance
        category_gaps = self._analyze_categories(coverage_by_category)
        gaps.extend(category_gaps)
        required_present = sum(1 for cat in _REQUIRED_CATEGORIES if coverage_by_category.get(cat, 0) > 0)
        coverage_by_surface["categories"] = required_present / len(_REQUIRED_CATEGORIES) if _REQUIRED_CATEGORIES else 1.0

        # Overall score
        if coverage_by_surface:
            overall = sum(coverage_by_surface.values()) / len(coverage_by_surface)
        else:
            overall = 0.0

        # Recommendations
        for gap in sorted(gaps, key=lambda g: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(g.severity, 4)):
            recommendations.append(gap.description)

        return CoverageReport(
            total_cases=len(existing_cases),
            gaps=gaps,
            coverage_by_surface=coverage_by_surface,
            coverage_by_category=coverage_by_category,
            overall_score=overall,
            recommendations=recommendations[:10],
        )

    def fill_gaps(
        self,
        card: Any,
        existing_cases: list[dict[str, Any]],
        generator: Any = None,
    ) -> list[Any]:
        """Analyze coverage and auto-generate cases to fill gaps.

        Args:
            card: AgentCardModel
            existing_cases: current test cases
            generator: CardCaseGenerator instance (optional)

        Returns:
            List of newly generated cases to add.
        """
        report = self.analyze(card, existing_cases)

        if not report.gaps:
            return []

        if generator is None:
            # Import here to avoid circular dependency
            from evals.card_case_generator import CardCaseGenerator
            generator = CardCaseGenerator()

        new_cases: list[Any] = []
        filled_surfaces: set[str] = set()

        for gap in report.gaps:
            if gap.severity not in ("critical", "high"):
                continue

            needed = gap.recommended_count - gap.current_count
            if needed <= 0:
                continue

            surface_key = f"{gap.surface}:{gap.component_name}"
            if surface_key in filled_surfaces:
                continue
            filled_surfaces.add(surface_key)

            # Generate cases for this specific gap
            if gap.surface == "routing_rule":
                cases = generator.generate_routing_cases(card, count=needed)
                # Filter to only cases targeting this specialist
                cases = [c for c in cases if c.expected_specialist == gap.component_name][:needed]
                new_cases.extend(cases)
            elif gap.surface == "tool":
                cases = generator.generate_tool_cases(card, count=needed)
                cases = [c for c in cases if c.expected_tool == gap.component_name][:needed]
                new_cases.extend(cases)
            elif gap.surface == "guardrail":
                cases = generator.generate_safety_cases(card, count=needed)
                new_cases.extend(cases[:needed])
            elif gap.surface == "sub_agent":
                cases = generator.generate_sub_agent_cases(card, count=needed)
                cases = [c for c in cases if c.expected_specialist == gap.component_name][:needed]
                new_cases.extend(cases)
            elif gap.surface == "category":
                if gap.component_name == "safety":
                    new_cases.extend(generator.generate_safety_cases(card, count=needed)[:needed])
                elif gap.component_name == "edge_cases":
                    new_cases.extend(generator.generate_edge_cases(card)[:needed])
                elif gap.component_name == "routing":
                    new_cases.extend(generator.generate_routing_cases(card, count=needed)[:needed])
                elif gap.component_name == "tool_usage":
                    new_cases.extend(generator.generate_tool_cases(card, count=needed)[:needed])
                else:
                    new_cases.extend(generator.generate_routing_cases(card, count=needed)[:needed])

        return new_cases

    # ------------------------------------------------------------------
    # Gap detection per surface
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_routing(
        card: Any,
        cases_by_specialist: dict[str, list[dict]],
    ) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        for rule in getattr(card, "routing_rules", []):
            target = rule.target
            cases = cases_by_specialist.get(target, [])
            count = len(cases)

            if count == 0:
                gaps.append(CoverageGap(
                    surface="routing_rule",
                    component_name=target,
                    gap_type="no_cases",
                    current_count=0,
                    recommended_count=_MIN_CASES_PER_ROUTE,
                    description=f"No test cases route to '{target}' specialist. Add at least {_MIN_CASES_PER_ROUTE} cases.",
                    severity="critical",
                ))
            elif count < _MIN_CASES_PER_ROUTE:
                gaps.append(CoverageGap(
                    surface="routing_rule",
                    component_name=target,
                    gap_type="low_coverage",
                    current_count=count,
                    recommended_count=_MIN_CASES_PER_ROUTE,
                    description=f"Only {count} case(s) for '{target}' specialist. Recommend at least {_MIN_CASES_PER_ROUTE}.",
                    severity="high",
                ))
        return gaps

    @staticmethod
    def _analyze_tools(
        card: Any,
        cases_by_tool: dict[str, list[dict]],
    ) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        all_tools = getattr(card, "all_tool_names", lambda: [])()
        for tool_name in all_tools:
            cases = cases_by_tool.get(tool_name, [])
            if not cases:
                gaps.append(CoverageGap(
                    surface="tool",
                    component_name=tool_name,
                    gap_type="no_cases",
                    current_count=0,
                    recommended_count=_MIN_CASES_PER_TOOL,
                    description=f"No test cases exercise the '{tool_name}' tool. Add at least {_MIN_CASES_PER_TOOL}.",
                    severity="high",
                ))
        return gaps

    @staticmethod
    def _analyze_safety(
        card: Any,
        safety_cases: list[dict],
    ) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        guardrails = getattr(card, "guardrails", [])
        count = len(safety_cases)

        if count < _MIN_SAFETY_CASES:
            gaps.append(CoverageGap(
                surface="guardrail",
                component_name="safety_overall",
                gap_type="no_adversarial" if count == 0 else "low_coverage",
                current_count=count,
                recommended_count=_MIN_SAFETY_CASES,
                description=f"Only {count} safety/adversarial case(s). Recommend at least {_MIN_SAFETY_CASES}.",
                severity="critical" if count == 0 else "high",
            ))

        # Check each guardrail has at least one test
        for guardrail in guardrails:
            # Simple heuristic: check if any safety case mentions the guardrail name
            has_coverage = any(
                guardrail.name.lower() in str(c.get("user_message", "")).lower()
                or guardrail.name.lower() in str(c.get("category", "")).lower()
                for c in safety_cases
            )
            if not has_coverage:
                gaps.append(CoverageGap(
                    surface="guardrail",
                    component_name=guardrail.name,
                    gap_type="no_cases",
                    current_count=0,
                    recommended_count=1,
                    description=f"No test case exercises the '{guardrail.name}' guardrail.",
                    severity="medium",
                ))
        return gaps

    @staticmethod
    def _analyze_sub_agents(
        card: Any,
        cases_by_specialist: dict[str, list[dict]],
    ) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        for sa in getattr(card, "sub_agents", []):
            cases = cases_by_specialist.get(sa.name, [])
            if not cases:
                gaps.append(CoverageGap(
                    surface="sub_agent",
                    component_name=sa.name,
                    gap_type="no_cases",
                    current_count=0,
                    recommended_count=2,
                    description=f"No test cases target the '{sa.name}' sub-agent.",
                    severity="high",
                ))
        return gaps

    @staticmethod
    def _analyze_categories(
        coverage_by_category: dict[str, int],
    ) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        for category, min_count in _REQUIRED_CATEGORIES.items():
            actual = coverage_by_category.get(category, 0)
            if actual < min_count:
                gaps.append(CoverageGap(
                    surface="category",
                    component_name=category,
                    gap_type="no_cases" if actual == 0 else "low_coverage",
                    current_count=actual,
                    recommended_count=min_count,
                    description=f"Category '{category}' has {actual} case(s), recommend at least {min_count}.",
                    severity="high" if actual == 0 else "medium",
                ))
        return gaps
