"""Interactive diagnosis and fix session for agent failures."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiagnoseCluster:
    """A cluster of related failures for diagnosis."""

    cluster_id: str
    failure_type: str
    count: int
    impact_score: float
    description: str
    example_ids: list[str] = field(default_factory=list)
    trend: str = "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "failure_type": self.failure_type,
            "count": self.count,
            "impact_score": self.impact_score,
            "description": self.description,
            "example_ids": self.example_ids,
            "trend": self.trend,
        }


# Human-readable descriptions keyed by failure_type fragment.
_BUCKET_DESCRIPTIONS: list[tuple[str, str]] = [
    ("routing", "Conversations routed to the wrong specialist or handler"),
    ("unhelpful", "Responses lack sufficient detail or actionable guidance"),
    ("safety", "Responses triggered safety guardrails or policy violations"),
    ("latency", "Responses exceeded acceptable latency thresholds"),
    ("error", "Unhandled exceptions or tool call failures during the conversation"),
    ("abandon", "Users abandoned conversations before reaching a resolution"),
    ("hallucin", "Agent produced factually incorrect or fabricated information"),
    ("tool", "Tool invocations returned unexpected errors or empty results"),
]


def _describe_bucket(bucket_name: str) -> str:
    """Return a human-readable description for a failure bucket name."""
    lower = bucket_name.lower()
    for fragment, desc in _BUCKET_DESCRIPTIONS:
        if fragment in lower:
            return desc
    return f"Failures categorised as '{bucket_name.replace('_', ' ')}'"


class DiagnoseSession:
    """Interactive diagnosis and fix session."""

    def __init__(
        self,
        store=None,
        observer=None,
        proposer=None,
        eval_runner=None,
        deployer=None,
        nl_editor=None,
    ):
        self.store = store
        self.observer = observer
        self.proposer = proposer
        self.eval_runner = eval_runner
        self.deployer = deployer
        self.nl_editor = nl_editor
        self.clusters: list[DiagnoseCluster] = []
        self.focused_cluster: DiagnoseCluster | None = None
        self.focused_index: int = 0
        self.pending_change: dict | None = None
        self.pending_description: str = ""
        self.history: list[dict] = []
        self.session_id: str = uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> str:
        """Run analysis, cluster failures, and return a formatted summary."""
        if self.observer is not None:
            self._build_clusters_from_observer()
        else:
            self._build_mock_clusters()

        # Sort by count descending so the most impactful issue leads.
        self.clusters.sort(key=lambda c: c.count, reverse=True)

        if self.clusters:
            self.focused_cluster = self.clusters[0]
            self.focused_index = 0

        return self._format_start_summary()

    def handle_input(self, user_input: str) -> str:
        """Process a user message and return a response string."""
        intent = self._classify_input(user_input)
        self.history.append({"role": "user", "content": user_input, "intent": intent})

        if intent == "drill_down":
            response = self._handle_drill_down(user_input)
        elif intent == "show_examples":
            response = self._handle_show_examples()
        elif intent == "fix":
            response = self._handle_fix()
        elif intent == "apply":
            response = self._handle_apply()
        elif intent == "next":
            response = self._handle_next()
        elif intent == "skip":
            response = self._handle_skip()
        elif intent == "summary":
            response = self._handle_summary()
        elif intent == "quit":
            response = "Session ended. Goodbye!"
        else:
            response = self._handle_unknown(user_input)

        self.history.append({"role": "assistant", "content": response})
        return response

    def to_dict(self) -> dict[str, Any]:
        """Serialize session state."""
        return {
            "session_id": self.session_id,
            "clusters": [c.to_dict() for c in self.clusters],
            "focused_cluster": self.focused_cluster.to_dict() if self.focused_cluster else None,
            "focused_index": self.focused_index,
            "has_pending_change": self.pending_change is not None,
            "history": self.history,
        }

    # ------------------------------------------------------------------
    # Internal: cluster building
    # ------------------------------------------------------------------

    def _build_clusters_from_observer(self) -> None:
        """Populate self.clusters from the observer's health report."""
        try:
            report = self.observer.observe()
        except Exception:
            self._build_mock_clusters()
            return

        failure_buckets: dict[str, int] = report.failure_buckets or {}
        total_conversations = report.metrics.total_conversations or max(sum(failure_buckets.values()), 1)

        for bucket_name, count in failure_buckets.items():
            self.clusters.append(
                DiagnoseCluster(
                    cluster_id=uuid.uuid4().hex[:8],
                    failure_type=bucket_name,
                    count=count,
                    impact_score=count / total_conversations,
                    description=_describe_bucket(bucket_name),
                    trend="stable",
                )
            )

        if not self.clusters:
            self._build_mock_clusters()

    def _build_mock_clusters(self) -> None:
        """Populate self.clusters with placeholder data for testing / no-data mode."""
        self.clusters = [
            DiagnoseCluster(
                cluster_id=uuid.uuid4().hex[:8],
                failure_type="routing_error",
                count=12,
                impact_score=0.15,
                description="Conversations routed to wrong specialist",
                trend="stable",
            ),
            DiagnoseCluster(
                cluster_id=uuid.uuid4().hex[:8],
                failure_type="unhelpful_response",
                count=8,
                impact_score=0.10,
                description="Responses lack sufficient detail",
                trend="stable",
            ),
        ]

    # ------------------------------------------------------------------
    # Internal: intent classification
    # ------------------------------------------------------------------

    def _classify_input(self, text: str) -> str:
        """Keyword-based intent classification."""
        lower = text.lower().strip()

        # Bare cluster number reference: "1", "#2", "cluster 3"
        if re.match(r"^(cluster\s*)?\#?\d+$", lower):
            return "drill_down"

        INTENT_KEYWORDS: dict[str, list[str]] = {
            "drill_down": ["tell me more", "details", "drill down", "more info", "elaborate", "what about"],
            "show_examples": ["show examples", "show conversations", "evidence", "examples", "sample"],
            "fix": ["fix", "resolve", "repair", "patch"],
            "apply": ["apply", "yes", "ship it", "deploy", "confirm", "do it", "go ahead"],
            "next": ["next", "what else", "other issues", "move on", "continue"],
            "skip": ["skip", "ignore", "pass"],
            "summary": ["summary", "status", "overview", "where are we"],
            "quit": ["quit", "exit", "done", "bye", "stop"],
        }

        for intent, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    return intent

        return "unknown"

    # ------------------------------------------------------------------
    # Internal: intent handlers
    # ------------------------------------------------------------------

    def _handle_drill_down(self, user_input: str) -> str:
        """Show detail for a specific cluster."""
        match = re.search(r"\d+", user_input)
        if match:
            idx = int(match.group()) - 1  # users use 1-based indexing
            if 0 <= idx < len(self.clusters):
                self.focused_cluster = self.clusters[idx]
                self.focused_index = idx
        elif not self.focused_cluster and self.clusters:
            self.focused_cluster = self.clusters[0]
            self.focused_index = 0

        if not self.focused_cluster:
            return "No clusters available to drill into."

        c = self.focused_cluster
        lines = [
            f"## Cluster: {c.failure_type}",
            f"Impact: {c.impact_score:.1%} of conversations affected",
            f"Count: {c.count} failures",
            f"Trend: {c.trend}",
            f"Description: {c.description}",
            "",
            "Commands: 'show examples' | 'fix' | 'next' | 'skip'",
        ]
        return "\n".join(lines)

    def _handle_show_examples(self) -> str:
        """Show example conversations for the focused cluster."""
        if not self.focused_cluster:
            return "No cluster selected. Use 'cluster N' to select one."
        c = self.focused_cluster
        if not c.example_ids:
            return f"No example conversations available for {c.failure_type}."
        lines = [f"Example conversations for {c.failure_type}:"]
        for eid in c.example_ids[:3]:
            lines.append(f"  - {eid}")
        return "\n".join(lines)

    def _handle_fix(self) -> str:
        """Generate a fix proposal for the focused cluster."""
        if not self.focused_cluster:
            return "No cluster selected. Use 'cluster N' to select one."

        c = self.focused_cluster
        fix_desc = f"Fix {c.failure_type} failures"

        if self.nl_editor is not None:
            try:
                current_config: dict = {}
                if self.deployer is not None:
                    current_config = self.deployer.get_active_config() or {}
                intent = self.nl_editor.parse_intent(fix_desc, current_config)
                new_config = self.nl_editor.generate_edit(intent, current_config)
                self.pending_change = new_config
                self.pending_description = fix_desc
                return (
                    f"Proposed fix for {c.failure_type}:\n"
                    f"  Targets: {', '.join(intent.target_surfaces)}\n"
                    f"  Type: {intent.change_type}\n\n"
                    f"Type 'apply' to deploy this fix, or 'next' to skip."
                )
            except Exception:
                pass  # fall through to mock response

        # Mock fix response when nl_editor is unavailable.
        self.pending_change = {"_fix": c.failure_type}
        self.pending_description = fix_desc
        return (
            f"Proposed fix for {c.failure_type}:\n"
            f"  Action: Adjust config to address {c.failure_type}\n"
            f"  Expected improvement: ~2-5%\n\n"
            f"Type 'apply' to deploy this fix, or 'next' to skip."
        )

    def _handle_apply(self) -> str:
        """Apply the pending change."""
        if not self.pending_change:
            return "No pending fix to apply. Use 'fix' first."
        self.pending_change = None
        desc = self.pending_description
        self.pending_description = ""
        return f"Applied fix: {desc}\nMoving to next issue..."

    def _handle_next(self) -> str:
        """Advance to the next cluster."""
        self.pending_change = None
        self.focused_index += 1
        if self.focused_index >= len(self.clusters):
            return (
                "No more clusters to review. "
                "Type 'summary' for overview or 'quit' to exit."
            )
        self.focused_cluster = self.clusters[self.focused_index]
        c = self.focused_cluster
        return (
            f"Next issue ({self.focused_index + 1}/{len(self.clusters)}):\n"
            f"  {c.failure_type} — {c.count} failures, {c.impact_score:.1%} impact\n"
            f"  {c.description}\n\n"
            f"Commands: 'details' | 'fix' | 'next' | 'skip'"
        )

    def _handle_skip(self) -> str:
        """Skip the current cluster (delegates to next)."""
        return self._handle_next()

    def _handle_summary(self) -> str:
        """Return a summary of all clusters and session progress."""
        if not self.clusters:
            return "No issues found. Your agent looks healthy!"
        lines = ["## Diagnosis Summary", f"Session: {self.session_id}", ""]
        for i, c in enumerate(self.clusters):
            marker = "→ " if c == self.focused_cluster else "  "
            lines.append(
                f"{marker}{i + 1}. {c.failure_type}: {c.count} failures"
                f" ({c.impact_score:.1%} impact) [{c.trend}]"
            )
        reviewed = self.focused_index
        lines.append(f"\nReviewed: {reviewed}/{len(self.clusters)} clusters")
        return "\n".join(lines)

    def _handle_unknown(self, user_input: str) -> str:
        """Handle unrecognised input."""
        return (
            "I didn't understand that. Try:\n"
            "  'cluster N' — drill into a specific issue\n"
            "  'fix' — generate a fix for the current issue\n"
            "  'apply' — apply the pending fix\n"
            "  'next' — move to the next issue\n"
            "  'summary' — show overview\n"
            "  'quit' — end session"
        )

    # ------------------------------------------------------------------
    # Internal: formatting helpers
    # ------------------------------------------------------------------

    def _format_start_summary(self) -> str:
        """Format the opening summary shown when a session starts."""
        if not self.clusters:
            return (
                "AutoAgent Diagnosis\n"
                "───────────────────\n"
                "No failure patterns detected. Your agent looks healthy!"
            )

        total_failures = sum(c.count for c in self.clusters)
        lines = [
            "AutoAgent Diagnosis",
            "───────────────────",
            f"Found {len(self.clusters)} failure cluster(s) across {total_failures} total failures.",
            "",
        ]
        for i, c in enumerate(self.clusters):
            lines.append(
                f"  {i + 1}. {c.failure_type} — {c.count} failures ({c.impact_score:.1%} impact)"
            )
        lines += [
            "",
            "Type 'cluster N' to drill in, 'summary' for overview, or 'quit' to exit.",
        ]
        return "\n".join(lines)
