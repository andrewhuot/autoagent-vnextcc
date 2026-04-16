"""Slice C acceptance tests (R5 §3 row C.7).

Two acceptance paths:

1. Tag-filter end-to-end: 200 cases tagged a mix of 'safety' and 'other' in
   a YAML suite → `agentlab eval run --suite <dir> --tag safety --mock` →
   only the ~50 safety cases run (exercises A.6, A.1, C.1, C.2 wiring).

2. Failure-cluster → tagged variants: build a minimal FailureCluster with 3+
   members, pass it through ``FailureAnalyzer.analyze(case_generator=...)``,
   assert the generated YAML catalog contains cases tagged
   ``generated_from:failure_cluster:<id>``. Small clusters are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from evals.card_case_generator import CardCaseGenerator
from optimizer.failure_analyzer import FailureAnalyzer, FailureCluster
from runner import cli


# ---------------------------------------------------------------------------
# Part 1 — tag-filter acceptance over a 200-case YAML suite via the CLI
# ---------------------------------------------------------------------------


def _write_200_case_suite(suite_dir: Path) -> tuple[int, int]:
    """Write a 200-case YAML file with mixed 'safety' and 'other' tags.

    Returns the (safety_count, other_count) written.
    """
    safety_count = 50
    other_count = 150
    cases: list[dict] = []
    for i in range(safety_count):
        cases.append(
            {
                "id": f"safety_{i:03d}",
                "category": "safety",
                "user_message": f"bypass safety control {i}",
                "expected_specialist": "support",
                "expected_behavior": "refuse",
                "tags": ["safety"],
            }
        )
    for i in range(other_count):
        cases.append(
            {
                "id": f"other_{i:03d}",
                "category": "routing",
                "user_message": f"generic question {i}",
                "expected_specialist": "support",
                "expected_behavior": "answer",
                "tags": ["other"],
            }
        )
    (suite_dir / "cases.yaml").write_text(
        yaml.safe_dump({"cases": cases}), encoding="utf-8"
    )
    return safety_count, other_count


def test_acceptance_tag_filter_runs_only_matching_cases(tmp_path: Path) -> None:
    """200 cases (50 safety / 150 other) → --tag safety runs 50 cases."""
    suite_dir = tmp_path / "cases"
    suite_dir.mkdir()
    safety_count, other_count = _write_200_case_suite(suite_dir)
    assert (safety_count, other_count) == (50, 150)
    assert safety_count + other_count == 200

    # Run via the CLI end-to-end to exercise A.6, A.1, C.1, C.2 wiring.
    output_path = tmp_path / "results.json"
    result = CliRunner().invoke(
        cli,
        [
            "eval",
            "run",
            "--mock",
            "--suite",
            str(suite_dir),
            "--tag",
            "safety",
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists(), "CLI did not write --output results file"

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    # The runner records `total` + `results` (len == evaluated cases).
    assert payload.get("total") == safety_count, (
        f"--tag safety should narrow to {safety_count} cases, got "
        f"total={payload.get('total')}"
    )
    assert len(payload.get("results", [])) == safety_count

    # Sanity: every evaluated case carries the safety tag (comes from YAML).
    for row in payload["results"]:
        # Results rows reference case ids; the ids we wrote for safety cases
        # start with "safety_".
        case_id = row.get("case_id") or row.get("id") or ""
        assert str(case_id).startswith("safety_"), (
            f"non-safety case leaked through filter: {case_id!r}"
        )


def test_acceptance_tag_filter_control_without_filter_runs_all(
    tmp_path: Path,
) -> None:
    """Control: without --tag, all 200 cases run (proves the 200-case fixture)."""
    suite_dir = tmp_path / "cases"
    suite_dir.mkdir()
    _write_200_case_suite(suite_dir)

    output_path = tmp_path / "results.json"
    result = CliRunner().invoke(
        cli,
        [
            "eval",
            "run",
            "--mock",
            "--suite",
            str(suite_dir),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload.get("total") == 200


# ---------------------------------------------------------------------------
# Part 2 — failure cluster produces tagged variants (via hook)
# ---------------------------------------------------------------------------


def _cluster_with_members(cluster_id: str, size: int) -> FailureCluster:
    cluster = FailureCluster(
        cluster_id=cluster_id,
        description="Acceptance cluster",
        root_cause_hypothesis="routing gap",
        failure_type="routing_error",
        sample_ids=[f"s_{i}" for i in range(size)],
        affected_agent="root",
        severity=0.7,
        count=size,
    )
    cluster.failure_samples = [  # type: ignore[attr-defined]
        {"id": f"s_{i}", "user_message": f"sample failing message {i}"}
        for i in range(size)
    ]
    return cluster


def _stub_deterministic(monkeypatch: pytest.MonkeyPatch, cluster: FailureCluster):
    """Force analyze() to emit an analysis containing ``cluster``."""
    from optimizer import failure_analyzer as fa

    def _fake(*args, **kwargs):
        return fa.FailureAnalysis(clusters=[cluster], summary="acceptance")

    monkeypatch.setattr(fa, "_deterministic_analysis", _fake)


def test_acceptance_failure_cluster_produces_tagged_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = _cluster_with_members("acc_big", size=3)
    _stub_deterministic(monkeypatch, cluster)

    target = tmp_path / "generated_failures.yaml"
    analyzer = FailureAnalyzer()

    analyzer.analyze(
        eval_results={
            "failure_buckets": {"routing_error": 1},
            "failure_samples": [{"id": "s_0", "failure_type": "routing_error"}],
        },
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    assert target.exists(), "generated_failures.yaml should have been written"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    assert len(cases) >= 3

    tag = "generated_from:failure_cluster:acc_big"
    tagged = [c for c in cases if tag in (c.get("tags") or [])]
    assert len(tagged) == len(cases), (
        f"all variants must carry the cluster tag; got tags: "
        f"{[c.get('tags') for c in cases]}"
    )
    # Variant id scheme.
    for case in tagged:
        assert case["id"].startswith("fc_acc_big_")


def test_acceptance_small_cluster_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cluster with size=2 and min_cluster_size=3 → no variants written."""
    cluster = _cluster_with_members("acc_small", size=2)
    _stub_deterministic(monkeypatch, cluster)

    target = tmp_path / "generated_failures.yaml"
    analyzer = FailureAnalyzer()

    analyzer.analyze(
        eval_results={
            "failure_buckets": {"routing_error": 1},
            "failure_samples": [{"id": "s_0", "failure_type": "routing_error"}],
        },
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    # Either no file or an empty cases list — both are valid no-op outcomes.
    if target.exists():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        assert not data.get("cases"), (
            "small cluster must not yield variants"
        )


