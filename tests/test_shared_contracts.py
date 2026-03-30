"""Tests for shared Python domain contracts."""

from __future__ import annotations

from shared.contracts import (
    BuildArtifact,
    DeploymentTarget,
    ExperimentRecord,
    ReleaseObject,
    SkillRecord,
    TranscriptReport,
)


def test_build_artifact_round_trips() -> None:
    artifact = BuildArtifact(
        id="build-001",
        created_at="2026-03-29T12:00:00Z",
        updated_at="2026-03-29T12:01:00Z",
        source="prompt",
        status="draft",
        config_yaml="agent: test",
        prompt_used="Build a test agent",
        transcript_report_id=None,
        builder_session_id="session-1",
        eval_draft="eval: []",
        starter_config_path="configs/v001.yaml",
        selector="latest",
        metadata={"title": "Test Agent"},
    )

    assert BuildArtifact.from_dict(artifact.to_dict()) == artifact


def test_experiment_record_round_trips() -> None:
    record = ExperimentRecord(
        experiment_id="exp-001",
        created_at=1711713600.0,
        hypothesis="Improve routing",
        touched_surfaces=["prompt"],
        touched_agents=["root"],
        diff_summary="Rewrote root prompt",
        eval_set_versions={"golden": "abc123"},
        replay_set_hash="replay-1",
        baseline_sha="base",
        candidate_sha="cand",
        risk_class="low",
        deployment_policy="pr_only",
        rollback_handle="rollback-1",
        total_experiment_cost=1.5,
        status="accepted",
        result_summary="Better quality",
        operator_name="rewrite_prompt",
        baseline_scores={"quality": 0.7},
        candidate_scores={"quality": 0.8},
        significance_p_value=0.03,
        significance_delta=0.1,
    )

    assert ExperimentRecord.from_dict(record.to_dict()) == record


def test_transcript_report_round_trips() -> None:
    report = TranscriptReport(
        report_id="report-001",
        archive_name="transcripts.zip",
        created_at=1711713600.0,
        conversation_count=3,
        languages=["en"],
        missing_intents=[{"intent": "refund", "count": 2, "reason": "missing policy"}],
        procedure_summaries=[{"intent": "refund", "steps": ["verify", "refund"]}],
        faq_entries=[{"intent": "refund", "question": "How do I get a refund?"}],
        workflow_suggestions=[{"title": "Escalate sooner", "description": "Route earlier"}],
        suggested_tests=[{"name": "refund flow", "user_message": "I want a refund"}],
        insights=[{"insight_id": "insight-1", "title": "Refund gap"}],
        knowledge_asset={"asset_id": "asset-1", "entry_count": 2},
        conversations=[{"conversation_id": "c-1", "user_message": "help"}],
    )

    assert TranscriptReport.from_dict(report.to_dict()) == report


def test_skill_record_round_trips() -> None:
    record = SkillRecord(
        skill_id="skill-001",
        name="routing_rewrite",
        kind="build",
        version="1.0.0",
        domain="customer-support",
        status="active",
        description="Improve routing",
        tags=["routing", "prompt"],
        effectiveness={"times_applied": 3, "success_rate": 0.66},
        source="registry",
        created_at="2026-03-29T12:00:00Z",
        updated_at="2026-03-29T12:00:00Z",
        metadata={"owner": "autoagent"},
    )

    assert SkillRecord.from_dict(record.to_dict()) == record


def test_deployment_target_round_trips() -> None:
    target = DeploymentTarget(
        target_id="deploy-001",
        name="production",
        kind="config",
        strategy="canary",
        environment="prod",
        description="Primary production target",
        status="active",
        endpoint="https://example.invalid/deploy",
        metadata={"region": "us-east-1"},
    )

    assert DeploymentTarget.from_dict(target.to_dict()) == target


def test_release_object_round_trips() -> None:
    release = ReleaseObject(
        release_id="rel-001",
        version="v001",
        status="SIGNED",
        code_diff={"files": ["runner.py"]},
        config_diff={"configs/v001.yaml": {"changed": True}},
        prompt_diff={"system_prompt": {"before": "a", "after": "b"}},
        dataset_version="dataset-1",
        eval_results={"quality": 0.92},
        grader_versions={"default": "1.0"},
        judge_versions={"safety": "2.0"},
        skill_versions={"routing": "1.1"},
        model_version="gpt-test",
        risk_class="low",
        approval_chain=[{"approved_by": "operator"}],
        canary_plan={"target": "prod"},
        rollback_instructions="Revert release",
        business_outcomes={"ticket_deflection": 0.1},
        created_at="2026-03-29T12:00:00Z",
        signed_at="2026-03-29T12:05:00Z",
        signature="sig-abc",
        metadata={"owner": "team-a"},
    )

    assert ReleaseObject.from_dict(release.to_dict()) == release
