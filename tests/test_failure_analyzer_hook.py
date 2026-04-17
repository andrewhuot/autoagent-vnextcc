"""Tests for the R5 C.6 FailureAnalyzer.analyze ``case_generator`` hook.

When ``case_generator`` is passed to ``analyze()``, clusters with size
``>= min_cluster_size`` drive ``CardCaseGenerator.generate_variants_from_cluster``
to emit tagged variants into ``generated_cases_path``. The variants are
tagged with ``generated_from:failure_cluster:<cluster_id>``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evals.card_case_generator import CardCaseGenerator, GeneratedCase
from optimizer.failure_analyzer import (
    FailureAnalysis,
    FailureAnalyzer,
    FailureCluster,
)


# ---------------------------------------------------------------------------
# Helpers: build a FailureAnalysis without running live LLM analysis
# ---------------------------------------------------------------------------


def _analysis_with_cluster(
    cluster_id: str,
    size: int,
    cluster_attr: str | None = "failure_samples",
) -> FailureAnalysis:
    """Construct an analysis holding a single cluster of the given size."""
    cluster = FailureCluster(
        cluster_id=cluster_id,
        description=f"{cluster_id} seed cluster",
        root_cause_hypothesis="test",
        failure_type="routing_error",
        sample_ids=[f"s_{i}" for i in range(size)],
        affected_agent="root",
        severity=0.5,
        count=size,
    )
    if cluster_attr:
        setattr(
            cluster,
            cluster_attr,
            [
                {"id": f"s_{i}", "user_message": f"seed message {i}"}
                for i in range(size)
            ],
        )
    return FailureAnalysis(
        clusters=[cluster],
        summary="test",
    )


def _stub_analyzer(monkeypatch, analysis: FailureAnalysis) -> FailureAnalyzer:
    """Return a FailureAnalyzer whose .analyze() returns ``analysis`` directly."""
    analyzer = FailureAnalyzer()

    # Patch the *internal* deterministic path to always return ``analysis``.
    # The public analyze() still runs its "no failures -> empty" shortcut,
    # so we craft an eval_results dict with at least one failure so the
    # call reaches the fallback path below.
    monkeypatch.setattr(
        "optimizer.failure_analyzer._deterministic_analysis",
        lambda *args, **kwargs: analysis,
    )
    return analyzer


def _baseline_eval_results() -> dict:
    return {
        "failure_buckets": {"routing_error": 1},
        "failure_samples": [{"id": "s_0", "failure_type": "routing_error"}],
    }


# ---------------------------------------------------------------------------
# Baseline: no case_generator -> current behavior unchanged, no file touched
# ---------------------------------------------------------------------------


def test_analyze_without_case_generator_unchanged_behavior(tmp_path: Path) -> None:
    analyzer = FailureAnalyzer()  # no router, no generator
    target = tmp_path / "generated_failures.yaml"

    result = analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
    )

    assert isinstance(result, FailureAnalysis)
    assert not target.exists(), "no case_generator must not create the file"


# ---------------------------------------------------------------------------
# Large cluster → variants written
# ---------------------------------------------------------------------------


def test_analyze_with_case_generator_writes_variants_for_large_cluster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analysis_with_cluster("big", size=5)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "generated_failures.yaml"

    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    assert target.exists()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "cases" in data
    cases = data["cases"]
    assert len(cases) >= 3
    for case in cases:
        assert "id" in case
        assert case["id"].startswith("fc_big_")
        assert "user_message" in case
        assert case.get("tags") == ["generated_from:failure_cluster:big"]


def test_analyze_skips_small_clusters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analysis_with_cluster("small", size=2)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "generated_failures.yaml"

    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    # No variants written since cluster size < min_cluster_size.
    if target.exists():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        assert not data.get("cases")


def test_analyze_idempotent_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analysis_with_cluster("idem", size=5)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "generated_failures.yaml"

    # First run
    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )
    first_ids = sorted(
        c["id"] for c in yaml.safe_load(target.read_text(encoding="utf-8"))["cases"]
    )

    # Second run — same cluster, same analysis. No duplicates.
    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )
    second_data = yaml.safe_load(target.read_text(encoding="utf-8"))
    second_ids = sorted(c["id"] for c in second_data["cases"])

    assert first_ids == second_ids
    assert len(second_ids) == len(set(second_ids))


def test_analyze_creates_file_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analysis_with_cluster("fresh", size=4)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "nested" / "does_not_yet_exist.yaml"
    assert not target.exists()

    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    assert target.exists()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "cases" in data and isinstance(data["cases"], list)


def test_analyze_variants_tag_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analysis_with_cluster("tagfmt", size=4)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "generated_failures.yaml"

    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    cases = yaml.safe_load(target.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        assert case["tags"] == ["generated_from:failure_cluster:tagfmt"]
        # Exact string shape — one key, two colons.
        assert case["tags"][0].count(":") == 2


def test_analyze_preserves_existing_cases_in_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing unrelated cases in the YAML survive the append."""
    analysis = _analysis_with_cluster("new_cluster", size=4)
    analyzer = _stub_analyzer(monkeypatch, analysis)
    target = tmp_path / "generated_failures.yaml"

    # Seed the file with a pre-existing case.
    target.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "preexisting_001",
                        "category": "baseline",
                        "user_message": "hello",
                        "expected_specialist": "support",
                        "expected_behavior": "answer",
                        "tags": ["manual"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    analyzer.analyze(
        eval_results=_baseline_eval_results(),
        agent_card_markdown="# agent",
        case_generator=CardCaseGenerator(),
        min_cluster_size=3,
        generated_cases_path=target,
    )

    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["cases"]]
    assert "preexisting_001" in ids
    assert any(i.startswith("fc_new_cluster_") for i in ids)
