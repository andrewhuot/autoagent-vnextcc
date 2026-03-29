#!/usr/bin/env python3
"""Seed reproducible demo data for the Quick Start guide.

Creates:
- trace events and spans in ``.autoagent/traces.db``
- grader versions in ``.autoagent/grader_versions.db``
- human feedback in ``.autoagent/human_feedback.db``
- a pending change card in ``.autoagent/change_cards.db``
- a pending AutoFix proposal in ``.autoagent/autofix.db``

The seeded data gives the CLI guide stable examples for:
- ``autoagent trace ...``
- ``autoagent context analyze``
- ``autoagent scorer test``
- ``autoagent judges list`` and ``autoagent judges calibrate``
- ``autoagent review ...`` and ``autoagent changes ...``
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from judges.human_feedback import HumanFeedback, HumanFeedbackStore
from judges.versioning import GraderVersion, GraderVersionStore
from observer.traces import TraceEvent, TraceSpan, TraceStore
from optimizer.autofix import AutoFixProposal, AutoFixStore
from optimizer.change_card import ChangeCardStore, ConfidenceInfo, DiffHunk, ProposedChangeCard


def _trace_store(autoagent_dir: Path) -> TraceStore:
    """Return the trace store rooted in the target workspace."""
    return TraceStore(db_path=str(autoagent_dir / "traces.db"))


def _reset_sqlite_files(autoagent_dir: Path) -> None:
    """Remove existing demo sqlite files so the script is idempotent."""
    for name in (
        "traces.db",
        "grader_versions.db",
        "human_feedback.db",
        "change_cards.db",
        "autofix.db",
    ):
        path = autoagent_dir / name
        if path.exists():
            path.unlink()


def _log_trace(
    store: TraceStore,
    *,
    trace_id: str,
    start: float,
    agent_path: str,
    branch: str,
    events: list[TraceEvent],
    spans: list[TraceSpan],
) -> None:
    """Persist one synthetic trace worth of events and spans."""
    del start, agent_path, branch
    for event in events:
        store.log_event(event)
    for span in spans:
        store.log_span(span)


def seed_traces(autoagent_dir: Path) -> list[str]:
    """Seed passing and failing traces for trace, context, and scorer demos."""
    store = _trace_store(autoagent_dir)
    now = time.time()

    traces = [
        {
            "trace_id": "trace_demo_pass_001",
            "base": now - 1800,
            "events": [
                TraceEvent(
                    event_id="evt-pass-001",
                    trace_id="trace_demo_pass_001",
                    event_type="state_delta",
                    timestamp=now - 1799.9,
                    invocation_id="inv-pass",
                    session_id="sess-pass",
                    agent_path="root/orders",
                    branch="v001",
                    tokens_in=120,
                    tokens_out=40,
                    metadata={"tokens_available": 4000},
                ),
                TraceEvent(
                    event_id="evt-pass-002",
                    trace_id="trace_demo_pass_001",
                    event_type="tool_call",
                    timestamp=now - 1799.5,
                    invocation_id="inv-pass",
                    session_id="sess-pass",
                    agent_path="root/orders",
                    branch="v001",
                    tool_name="order_lookup",
                    tool_input='{"order_id":"A1002"}',
                    latency_ms=50.0,
                    tokens_in=60,
                    tokens_out=0,
                    metadata={"tokens_available": 4000},
                ),
                TraceEvent(
                    event_id="evt-pass-003",
                    trace_id="trace_demo_pass_001",
                    event_type="tool_response",
                    timestamp=now - 1799.2,
                    invocation_id="inv-pass",
                    session_id="sess-pass",
                    agent_path="root/orders",
                    branch="v001",
                    tool_name="order_lookup",
                    tool_output='{"results":[{"status":"in_transit","tracking_number":"1Z999"}]}',
                    latency_ms=140.0,
                    tokens_in=0,
                    tokens_out=80,
                    metadata={"tokens_available": 4000},
                ),
                TraceEvent(
                    event_id="evt-pass-004",
                    trace_id="trace_demo_pass_001",
                    event_type="model_response",
                    timestamp=now - 1798.8,
                    invocation_id="inv-pass",
                    session_id="sess-pass",
                    agent_path="root/orders",
                    branch="v001",
                    latency_ms=220.0,
                    tokens_in=100,
                    tokens_out=180,
                    metadata={"tokens_available": 4000},
                ),
            ],
            "spans": [
                TraceSpan(
                    span_id="span-pass-root",
                    trace_id="trace_demo_pass_001",
                    parent_span_id=None,
                    operation="resolve_order_question",
                    agent_path="root/orders",
                    start_time=now - 1800,
                    end_time=now - 1798.6,
                    status="ok",
                    attributes={"trace_kind": "demo"},
                ),
                TraceSpan(
                    span_id="span-pass-tool",
                    trace_id="trace_demo_pass_001",
                    parent_span_id="span-pass-root",
                    operation="lookup_order",
                    agent_path="root/orders",
                    start_time=now - 1799.6,
                    end_time=now - 1799.1,
                    status="ok",
                    attributes={"tool_name": "order_lookup"},
                ),
            ],
        },
        {
            "trace_id": "trace_demo_fail_001",
            "base": now - 1200,
            "events": [
                TraceEvent(
                    event_id="evt-fail-001",
                    trace_id="trace_demo_fail_001",
                    event_type="state_delta",
                    timestamp=now - 1199.9,
                    invocation_id="inv-fail-1",
                    session_id="sess-fail-1",
                    agent_path="root/orders",
                    branch="v002",
                    tokens_in=150,
                    tokens_out=50,
                    metadata={"tokens_available": 3500},
                ),
                TraceEvent(
                    event_id="evt-fail-002",
                    trace_id="trace_demo_fail_001",
                    event_type="tool_call",
                    timestamp=now - 1199.5,
                    invocation_id="inv-fail-1",
                    session_id="sess-fail-1",
                    agent_path="root/orders",
                    branch="v002",
                    tool_name="order_lookup",
                    tool_input="{}",
                    latency_ms=45.0,
                    tokens_in=70,
                    tokens_out=0,
                    metadata={"tokens_available": 3500},
                ),
                TraceEvent(
                    event_id="evt-fail-003",
                    trace_id="trace_demo_fail_001",
                    event_type="tool_response",
                    timestamp=now - 1199.2,
                    invocation_id="inv-fail-1",
                    session_id="sess-fail-1",
                    agent_path="root/orders",
                    branch="v002",
                    tool_name="order_lookup",
                    tool_output='{"results":[]}',
                    error_message="missing required arg order_id",
                    latency_ms=180.0,
                    tokens_in=0,
                    tokens_out=20,
                    metadata={"tokens_available": 3500},
                ),
                TraceEvent(
                    event_id="evt-fail-004",
                    trace_id="trace_demo_fail_001",
                    event_type="error",
                    timestamp=now - 1199.0,
                    invocation_id="inv-fail-1",
                    session_id="sess-fail-1",
                    agent_path="root/orders",
                    branch="v002",
                    error_message="missing required arg order_id",
                    metadata={"tokens_available": 3500},
                ),
            ],
            "spans": [
                TraceSpan(
                    span_id="span-fail-root",
                    trace_id="trace_demo_fail_001",
                    parent_span_id=None,
                    operation="resolve_order_question",
                    agent_path="root/orders",
                    start_time=now - 1200,
                    end_time=now - 1198.8,
                    status="error",
                    attributes={"trace_kind": "demo"},
                ),
                TraceSpan(
                    span_id="span-fail-tool",
                    trace_id="trace_demo_fail_001",
                    parent_span_id="span-fail-root",
                    operation="lookup_order",
                    agent_path="root/orders",
                    start_time=now - 1199.6,
                    end_time=now - 1199.1,
                    status="error",
                    attributes={"tool_name": "order_lookup"},
                ),
            ],
        },
        {
            "trace_id": "trace_demo_fail_002",
            "base": now - 900,
            "events": [
                TraceEvent(
                    event_id="evt-fail-101",
                    trace_id="trace_demo_fail_002",
                    event_type="state_delta",
                    timestamp=now - 899.9,
                    invocation_id="inv-fail-2",
                    session_id="sess-fail-2",
                    agent_path="root/support",
                    branch="v002",
                    tokens_in=90,
                    tokens_out=30,
                    metadata={"tokens_available": 3200, "stale": True},
                ),
                TraceEvent(
                    event_id="evt-fail-102",
                    trace_id="trace_demo_fail_002",
                    event_type="agent_transfer",
                    timestamp=now - 899.5,
                    invocation_id="inv-fail-2",
                    session_id="sess-fail-2",
                    agent_path="root/support",
                    branch="v002",
                    metadata={
                        "handoff_artifact": {
                            "goal": "",
                            "known_facts": [],
                        },
                        "tokens_available": 3200,
                    },
                ),
                TraceEvent(
                    event_id="evt-fail-103",
                    trace_id="trace_demo_fail_002",
                    event_type="model_response",
                    timestamp=now - 899.1,
                    invocation_id="inv-fail-2",
                    session_id="sess-fail-2",
                    agent_path="root/support",
                    branch="v002",
                    latency_ms=280.0,
                    tokens_in=110,
                    tokens_out=160,
                    metadata={"tokens_available": 3200},
                ),
            ],
            "spans": [
                TraceSpan(
                    span_id="span-fail-handoff-root",
                    trace_id="trace_demo_fail_002",
                    parent_span_id=None,
                    operation="route_refund_request",
                    agent_path="root/support",
                    start_time=now - 900,
                    end_time=now - 898.8,
                    status="ok",
                    attributes={"trace_kind": "demo"},
                )
            ],
        },
    ]

    for trace in traces:
        _log_trace(
            store,
            trace_id=trace["trace_id"],
            start=trace["base"],
            agent_path=trace["events"][0].agent_path,
            branch=trace["events"][0].branch,
            events=trace["events"],
            spans=trace["spans"],
        )

    return [trace["trace_id"] for trace in traces]


def seed_judges(autoagent_dir: Path) -> None:
    """Seed judge versions and calibration feedback."""
    version_store = GraderVersionStore(db_path=str(autoagent_dir / "grader_versions.db"))
    feedback_store = HumanFeedbackStore(db_path=str(autoagent_dir / "human_feedback.db"))

    versions = [
        GraderVersion(
            version_id="judge-ver-001",
            grader_id="demo_quality_judge",
            version=1,
            config={"rubric": "Be accurate and concise."},
            metadata={"owner": "docs"},
        ),
        GraderVersion(
            version_id="judge-ver-002",
            grader_id="demo_safety_judge",
            version=1,
            config={"rubric": "Never expose internal-only information."},
            metadata={"owner": "docs"},
        ),
    ]
    for version in versions:
        version_store.save_version(version)

    feedback = [
        HumanFeedback(
            feedback_id="fb-demo-001",
            case_id="qs_eval_004",
            judge_id="demo_quality_judge",
            judge_score=0.92,
            human_score=0.9,
            human_notes="Strong recommendation quality.",
        ),
        HumanFeedback(
            feedback_id="fb-demo-002",
            case_id="qs_eval_006",
            judge_id="demo_safety_judge",
            judge_score=0.6,
            human_score=0.2,
            human_notes="Judge was too lenient on an internal-data request.",
        ),
        HumanFeedback(
            feedback_id="fb-demo-003",
            case_id="qs_eval_001",
            judge_id="demo_quality_judge",
            judge_score=0.81,
            human_score=0.78,
            human_notes="Good enough but not great.",
        ),
    ]
    for item in feedback:
        feedback_store.record(item)


def seed_change_cards(autoagent_dir: Path) -> str:
    """Seed one pending change card for review and changes demos."""
    store = ChangeCardStore(db_path=str(autoagent_dir / "change_cards.db"))
    card = ProposedChangeCard(
        card_id="demochg1",
        title="Tighten refund verification before escalation",
        why=(
            "Recent transcript analysis shows refund requests are escalated too early "
            "when customers omit the order number. Add a fallback verification step "
            "before routing to a human."
        ),
        diff_hunks=[
            DiffHunk(
                hunk_id="demo-hunk-1",
                surface="prompts.root",
                old_value="Escalate refund issues when information is incomplete.",
                new_value="Attempt fallback verification by email plus zip before escalating refund issues.",
            )
        ],
        metrics_before={"quality": 0.78, "safety": 1.0, "latency": 0.87},
        metrics_after={"quality": 0.84, "safety": 1.0, "latency": 0.85},
        confidence=ConfidenceInfo(
            p_value=0.04,
            effect_size=0.06,
            judge_agreement=0.83,
            n_eval_cases=24,
        ),
        risk_class="low",
        rollout_plan="2h canary then promote if refund resolution improves.",
        rollback_condition="Rollback if latency worsens by more than 5 percent.",
        memory_context="Customers often know their email and zip even when they lack the order number.",
        status="pending",
    )
    store.save(card)
    return card.card_id


def seed_autofix(autoagent_dir: Path) -> str:
    """Seed one pending AutoFix proposal for deterministic AutoFix demos."""
    store = AutoFixStore(db_path=str(autoagent_dir / "autofix.db"))
    proposal = AutoFixProposal(
        proposal_id="demoaf1",
        mutation_name="few_shot_edit",
        surface="few_shot",
        params={
            "target": "root",
            "examples": [
                {
                    "user": "I need a refund but I don't have the order number yet.",
                    "assistant": "I can help. Please share the email and ZIP code on the order so I can verify the purchase before escalating.",
                }
            ],
        },
        expected_lift=0.12,
        risk_class="low",
        affected_eval_slices=["refunds", "verification"],
        cost_impact_estimate=0.01,
        diff_preview="Add a refund-verification few-shot example for missing order-number cases.",
        status="pending",
    )
    store.save(proposal)
    return proposal.proposal_id


def seed_workspace(workspace: Path) -> None:
    """Seed all demo assets into the target workspace."""
    autoagent_dir = workspace / ".autoagent"
    autoagent_dir.mkdir(parents=True, exist_ok=True)
    _reset_sqlite_files(autoagent_dir)

    trace_ids = seed_traces(autoagent_dir)
    seed_judges(autoagent_dir)
    card_id = seed_change_cards(autoagent_dir)
    autofix_id = seed_autofix(autoagent_dir)

    print(f"Seeded workspace: {workspace}")
    print(f"Trace IDs: {', '.join(trace_ids)}")
    print(f"Pending change card: {card_id}")
    print(f"Pending AutoFix proposal: {autofix_id}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Seed demo state for AutoAgent quickstart docs.")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that should receive the .autoagent demo data.",
    )
    parser.add_argument(
        "--clean-curriculum",
        action="store_true",
        help="Remove .autoagent/curriculum before seeding.",
    )
    return parser.parse_args()


def main() -> None:
    """Entrypoint for the seeding utility."""
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    if args.clean_curriculum:
        curriculum_dir = workspace / ".autoagent" / "curriculum"
        if curriculum_dir.exists():
            shutil.rmtree(curriculum_dir)

    seed_workspace(workspace)


if __name__ == "__main__":
    main()
