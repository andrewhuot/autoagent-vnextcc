"""LLM-driven failure analysis with deterministic fallback.

Clusters failures from eval results, identifies root causes, and recommends
which agent surfaces to mutate. Uses the LLM router when available; falls
back to a rule-based deterministic analyzer otherwise.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from optimizer.providers import LLMRequest, LLMRouter

if TYPE_CHECKING:
    from evals.card_case_generator import CardCaseGenerator

logger = logging.getLogger(__name__)

# Maximum samples sent to the LLM to stay within token budget.
_MAX_FAILURE_SAMPLES = 20

# Maximum past optimization attempts included in the LLM prompt.
_MAX_PAST_ATTEMPTS = 10

# ---------------------------------------------------------------------------
# Deterministic mapping: failure bucket -> recommended MutationSurface value
# ---------------------------------------------------------------------------

_BUCKET_TO_SURFACE: dict[str, str] = {
    "routing_error": "routing",
    "tool_failure": "tool_contract",
    "hallucination": "instruction",
    "safety_violation": "policy",
    "timeout": "generation_settings",
    "unhelpful_response": "instruction",
    "invalid_output": "instruction",
}

# Default severity weights per bucket (higher = more impactful).
_BUCKET_SEVERITY: dict[str, float] = {
    "safety_violation": 1.0,
    "hallucination": 0.9,
    "routing_error": 0.8,
    "tool_failure": 0.7,
    "invalid_output": 0.6,
    "unhelpful_response": 0.5,
    "timeout": 0.4,
}

# Human-readable default approach for deterministic recommendations.
_BUCKET_APPROACH: dict[str, str] = {
    "routing_error": "Review and expand routing rule keywords/patterns to cover misrouted messages.",
    "tool_failure": "Audit tool contracts for schema mismatches, missing error handling, or timeout tuning.",
    "hallucination": "Strengthen instructions with grounding directives and factual constraints.",
    "safety_violation": "Tighten guardrail/policy definitions or add missing safety checks.",
    "timeout": "Increase timeout thresholds or reduce generation token limits.",
    "unhelpful_response": "Add quality-floor instructions and few-shot examples of good responses.",
    "invalid_output": "Add output format constraints and validation instructions.",
}

_VALID_SURFACES: set[str] = {
    "instruction",
    "few_shot",
    "tool_description",
    "model",
    "generation_settings",
    "callback",
    "context_caching",
    "memory_policy",
    "routing",
    "workflow",
    "skill",
    "policy",
    "tool_contract",
    "handoff_schema",
}

_VALID_FAILURE_TYPES: set[str] = set(_BUCKET_TO_SURFACE)

DEFAULT_GENERATED_FAILURE_CASES_PATH = Path("evals") / "cases" / "training" / "generated_failures.yaml"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FailureCluster:
    """A group of related failures sharing a common root cause."""

    cluster_id: str
    description: str
    root_cause_hypothesis: str
    failure_type: str  # matches observer/classifier buckets
    sample_ids: list[str] = field(default_factory=list)
    affected_agent: str = ""  # which agent/sub-agent path
    severity: float = 0.0  # 0-1
    count: int = 0


@dataclass
class SurfaceRecommendation:
    """A recommended mutation surface to address a failure cluster."""

    surface: str  # MutationSurface value
    agent_path: str  # which agent to modify (e.g. "root" or "root/support")
    confidence: float = 0.0  # 0-1
    reasoning: str = ""
    suggested_approach: str = ""
    priority: int = 1  # 1 = highest


@dataclass
class FailureAnalysis:
    """Complete failure analysis result."""

    clusters: list[FailureCluster] = field(default_factory=list)
    surface_recommendations: list[SurfaceRecommendation] = field(default_factory=list)
    severity_ranking: list[str] = field(default_factory=list)  # cluster_ids ordered by impact
    cross_cutting_patterns: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# LLM prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert AI agent debugger. You analyze evaluation failures for \
multi-agent systems and produce structured diagnoses.

Given an agent card (markdown representation of the agent), failure samples, \
failure bucket counts, and past optimization attempts, you must:

1. Cluster failures that share a common root cause.
2. For each cluster, hypothesize the root cause and identify the affected agent.
3. Recommend which agent surfaces (mutation targets) to change, with confidence \
and a concrete suggested approach.
4. Identify cross-cutting patterns that span multiple clusters.

Respond with a single JSON object (no markdown fences) matching this schema:

{
  "clusters": [
    {
      "cluster_id": "<unique id>",
      "description": "<what these failures have in common>",
      "root_cause_hypothesis": "<why they happen>",
      "failure_type": "<bucket name>",
      "sample_ids": ["<id>", ...],
      "affected_agent": "<agent name or path>",
      "severity": <0-1>,
      "count": <int>
    }
  ],
  "surface_recommendations": [
    {
      "surface": "<MutationSurface value>",
      "agent_path": "<which agent to modify>",
      "confidence": <0-1>,
      "reasoning": "<why this surface>",
      "suggested_approach": "<concrete action>",
      "priority": <int, 1=highest>
    }
  ],
  "severity_ranking": ["<cluster_id>", ...],
  "cross_cutting_patterns": ["<pattern description>", ...],
  "summary": "<1-3 sentence executive summary>"
}

Valid surface values: instruction, few_shot, tool_description, model, \
generation_settings, callback, context_caching, memory_policy, routing, \
workflow, skill, policy, tool_contract, handoff_schema."""


def _build_user_prompt(
    agent_card_markdown: str,
    failure_samples: list[dict[str, Any]],
    failure_buckets: dict[str, int],
    component_attributions: list[dict[str, Any]] | None,
    past_attempts: list[dict[str, Any]] | None,
) -> str:
    """Assemble the user-facing prompt with all available context."""
    parts: list[str] = []

    parts.append("## Agent Card\n")
    parts.append(agent_card_markdown.strip())

    parts.append("\n\n## Failure Buckets (counts)\n")
    for bucket, count in sorted(failure_buckets.items(), key=lambda kv: -kv[1]):
        if count > 0:
            parts.append(f"- {bucket}: {count}")

    trimmed = failure_samples[:_MAX_FAILURE_SAMPLES]
    if trimmed:
        parts.append(f"\n\n## Failure Samples ({len(trimmed)} of {len(failure_samples)})\n")
        parts.append(json.dumps(trimmed, indent=2, default=str))

    if component_attributions:
        parts.append("\n\n## Component Attributions\n")
        parts.append(json.dumps(component_attributions, indent=2, default=str))

    if past_attempts:
        trimmed_attempts = past_attempts[:_MAX_PAST_ATTEMPTS]
        parts.append(
            f"\n\n## Past Optimization Attempts ({len(trimmed_attempts)} of {len(past_attempts)})\n"
        )
        parts.append(json.dumps(trimmed_attempts, indent=2, default=str))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# JSON extraction from LLM response
# ---------------------------------------------------------------------------


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from free-form LLM text."""
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _validate_llm_analysis_payload(
    payload: dict[str, Any],
    *,
    known_sample_ids: set[str] | None = None,
) -> None:
    """Validate semantic constraints on an LLM-produced failure analysis payload."""
    raw_clusters = payload.get("clusters", [])
    if raw_clusters is None:
        raw_clusters = []
    if not isinstance(raw_clusters, list):
        raise ValueError("Failure analysis payload field 'clusters' must be a list")

    cluster_ids: set[str] = set()
    for index, raw_cluster in enumerate(raw_clusters):
        if not isinstance(raw_cluster, dict):
            raise ValueError(f"Cluster {index} must be a JSON object")

        cluster_id = str(raw_cluster.get("cluster_id", "")).strip()
        if not cluster_id:
            raise ValueError(f"Cluster {index} is missing a cluster_id")
        if cluster_id in cluster_ids:
            raise ValueError(f"Duplicate cluster_id in failure analysis payload: {cluster_id}")
        cluster_ids.add(cluster_id)

        failure_type = str(raw_cluster.get("failure_type", "")).strip()
        if failure_type and failure_type not in _VALID_FAILURE_TYPES:
            raise ValueError(f"Unknown failure type in failure analysis payload: {failure_type}")

        sample_ids = raw_cluster.get("sample_ids", [])
        if sample_ids is None:
            sample_ids = []
        if not isinstance(sample_ids, list):
            raise ValueError(f"Cluster {cluster_id} field 'sample_ids' must be a list")
        normalized_sample_ids = [str(sample_id) for sample_id in sample_ids]
        if known_sample_ids is not None:
            unknown_sample_ids = sorted(set(normalized_sample_ids) - known_sample_ids)
            if unknown_sample_ids:
                raise ValueError(
                    f"Cluster {cluster_id} references unknown sample ids: {', '.join(unknown_sample_ids[:3])}"
                )

        try:
            severity = float(raw_cluster.get("severity", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cluster {cluster_id} has a non-numeric severity") from exc
        if not 0.0 <= severity <= 1.0:
            raise ValueError(f"Cluster {cluster_id} severity must be between 0 and 1")

        try:
            count = int(raw_cluster.get("count", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cluster {cluster_id} has a non-integer count") from exc
        if count < 0:
            raise ValueError(f"Cluster {cluster_id} count must be non-negative")

    raw_recommendations = payload.get("surface_recommendations", [])
    if raw_recommendations is None:
        raw_recommendations = []
    if not isinstance(raw_recommendations, list):
        raise ValueError("Failure analysis payload field 'surface_recommendations' must be a list")

    for index, raw_rec in enumerate(raw_recommendations):
        if not isinstance(raw_rec, dict):
            raise ValueError(f"Surface recommendation {index} must be a JSON object")
        surface = str(raw_rec.get("surface", "")).strip()
        if surface not in _VALID_SURFACES:
            raise ValueError(f"Unknown surface in failure analysis payload: {surface}")
        try:
            confidence = float(raw_rec.get("confidence", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Surface recommendation {index} has a non-numeric confidence"
            ) from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"Surface recommendation {index} confidence must be between 0 and 1")
        try:
            priority = int(raw_rec.get("priority", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Surface recommendation {index} has a non-integer priority") from exc
        if priority < 1:
            raise ValueError(f"Surface recommendation {index} priority must be >= 1")

    severity_ranking = payload.get("severity_ranking", [])
    if severity_ranking is None:
        severity_ranking = []
    if not isinstance(severity_ranking, list):
        raise ValueError("Failure analysis payload field 'severity_ranking' must be a list")
    for cluster_id in severity_ranking:
        if str(cluster_id) not in cluster_ids:
            raise ValueError(
                f"Severity ranking references unknown cluster_id: {cluster_id}"
            )


def _parse_llm_analysis(
    payload: dict[str, Any],
    *,
    known_sample_ids: set[str] | None = None,
) -> FailureAnalysis:
    """Convert a validated JSON payload into a FailureAnalysis."""
    _validate_llm_analysis_payload(payload, known_sample_ids=known_sample_ids)

    clusters: list[FailureCluster] = []
    for raw_cluster in payload.get("clusters", []):
        clusters.append(FailureCluster(
            cluster_id=str(raw_cluster.get("cluster_id", uuid.uuid4().hex[:8])),
            description=str(raw_cluster.get("description", "")),
            root_cause_hypothesis=str(raw_cluster.get("root_cause_hypothesis", "")),
            failure_type=str(raw_cluster.get("failure_type", "unknown")),
            sample_ids=[str(sid) for sid in raw_cluster.get("sample_ids", [])],
            affected_agent=str(raw_cluster.get("affected_agent", "")),
            severity=float(raw_cluster.get("severity", 0.0)),
            count=int(raw_cluster.get("count", 0)),
        ))

    recommendations: list[SurfaceRecommendation] = []
    for raw_rec in payload.get("surface_recommendations", []):
        recommendations.append(SurfaceRecommendation(
            surface=str(raw_rec.get("surface", "instruction")),
            agent_path=str(raw_rec.get("agent_path", "root")),
            confidence=float(raw_rec.get("confidence", 0.0)),
            reasoning=str(raw_rec.get("reasoning", "")),
            suggested_approach=str(raw_rec.get("suggested_approach", "")),
            priority=int(raw_rec.get("priority", 1)),
        ))

    severity_ranking = [str(cid) for cid in payload.get("severity_ranking", [])]
    cross_cutting = [str(p) for p in payload.get("cross_cutting_patterns", [])]
    summary = str(payload.get("summary", ""))

    return FailureAnalysis(
        clusters=clusters,
        surface_recommendations=recommendations,
        severity_ranking=severity_ranking,
        cross_cutting_patterns=cross_cutting,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


def _deterministic_analysis(
    failure_buckets: dict[str, int],
    failure_samples: list[dict[str, Any]],
) -> FailureAnalysis:
    """Rule-based fallback when no LLM is available.

    Creates one cluster per non-zero bucket with a hardcoded surface mapping.
    """
    clusters: list[FailureCluster] = []
    recommendations: list[SurfaceRecommendation] = []

    # Sort by count descending for stable priority assignment.
    sorted_buckets = sorted(
        ((bucket, count) for bucket, count in failure_buckets.items() if count > 0),
        key=lambda kv: -kv[1],
    )

    total_failures = sum(count for _, count in sorted_buckets) or 1

    for priority_idx, (bucket, count) in enumerate(sorted_buckets, start=1):
        cluster_id = f"det-{bucket}"
        severity = min(1.0, (count / total_failures) * _BUCKET_SEVERITY.get(bucket, 0.5))

        # Collect sample IDs that match this bucket.
        sample_ids: list[str] = []
        for sample in failure_samples:
            sample_buckets = sample.get("failure_buckets", [])
            sample_type = sample.get("failure_type", "")
            if bucket in sample_buckets or bucket == sample_type:
                sid = str(sample.get("id", sample.get("sample_id", "")))
                if sid:
                    sample_ids.append(sid)

        clusters.append(FailureCluster(
            cluster_id=cluster_id,
            description=f"Failures classified as {bucket} ({count} occurrences).",
            root_cause_hypothesis=f"Agent configuration issues in the {_BUCKET_TO_SURFACE.get(bucket, 'instruction')} surface.",
            failure_type=bucket,
            sample_ids=sample_ids,
            affected_agent="root",
            severity=round(severity, 4),
            count=count,
        ))

        surface = _BUCKET_TO_SURFACE.get(bucket, "instruction")
        approach = _BUCKET_APPROACH.get(bucket, "Review and improve the agent configuration.")
        confidence = min(0.9, 0.5 + 0.1 * (count / total_failures))

        recommendations.append(SurfaceRecommendation(
            surface=surface,
            agent_path="root",
            confidence=round(confidence, 4),
            reasoning=f"{bucket} accounts for {count}/{total_failures} failures ({count * 100 // total_failures}%).",
            suggested_approach=approach,
            priority=priority_idx,
        ))

    severity_ranking = [c.cluster_id for c in clusters]

    # Basic cross-cutting pattern detection.
    cross_cutting: list[str] = []
    bucket_names = {b for b, _ in sorted_buckets}
    if "routing_error" in bucket_names and "unhelpful_response" in bucket_names:
        cross_cutting.append(
            "Routing errors and unhelpful responses may share a root cause: "
            "messages reaching the wrong specialist produce low-quality answers."
        )
    if "tool_failure" in bucket_names and "timeout" in bucket_names:
        cross_cutting.append(
            "Tool failures and timeouts may be related: failing tool calls "
            "can cause cascading latency spikes."
        )
    if "hallucination" in bucket_names and "safety_violation" in bucket_names:
        cross_cutting.append(
            "Hallucinations and safety violations may indicate insufficient "
            "grounding constraints in the instruction surface."
        )

    summary_parts = [f"{b}: {c}" for b, c in sorted_buckets[:3]]
    summary = (
        f"Deterministic analysis of {total_failures} failures across "
        f"{len(sorted_buckets)} buckets. Top issues: {', '.join(summary_parts)}."
    )

    return FailureAnalysis(
        clusters=clusters,
        surface_recommendations=recommendations,
        severity_ranking=severity_ranking,
        cross_cutting_patterns=cross_cutting,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Cluster-size helper (R5 C.6)
# ---------------------------------------------------------------------------


def _cluster_size(cluster: FailureCluster) -> int:
    """Return the effective size of a FailureCluster.

    Prefers the ``count`` attribute (the canonical member count on the
    dataclass); falls back to ``len(sample_ids)`` when ``count`` is zero.
    """
    count = int(getattr(cluster, "count", 0) or 0)
    if count > 0:
        return count
    sample_ids = getattr(cluster, "sample_ids", None) or []
    return len(sample_ids)


# ---------------------------------------------------------------------------
# FailureAnalyzer
# ---------------------------------------------------------------------------


class FailureAnalyzer:
    """Analyze eval failures and recommend agent surface mutations.

    Uses an LLM (via ``LLMRouter``) for deep analysis when available, and
    falls back to deterministic bucket-based analysis otherwise.
    """

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self.llm_router = llm_router

    def analyze(
        self,
        eval_results: dict[str, Any],
        agent_card_markdown: str,
        past_attempts: list[dict[str, Any]] | None = None,
        *,
        case_generator: "CardCaseGenerator | None" = None,
        min_cluster_size: int = 3,
        generated_cases_path: str | Path = DEFAULT_GENERATED_FAILURE_CASES_PATH,
    ) -> FailureAnalysis:
        """Run failure analysis on eval results.

        Parameters
        ----------
        eval_results:
            Dict containing at least ``failure_buckets`` (dict[str, int]) and
            optionally ``failure_samples`` (list[dict]), ``component_attributions``
            (list[dict]), and ``health_metrics`` (dict).
        agent_card_markdown:
            The rendered agent card in markdown form.
        past_attempts:
            Previous optimization attempt records, each a dict.
        case_generator:
            Optional ``CardCaseGenerator``. When provided, every cluster in
            the resulting analysis whose size is ``>= min_cluster_size`` drives
            ``generate_variants_from_cluster`` and the variants are appended
            (idempotently) to ``generated_cases_path`` as eval YAML cases
            tagged ``generated_from:failure_cluster:<cluster_id>``.
            When ``None`` (the default), behavior is unchanged.
        min_cluster_size:
            Minimum cluster size to trigger variant generation. Defaults to 3.
        generated_cases_path:
            Where to persist generated variants. Defaults to
            ``evals/cases/training/generated_failures.yaml`` so generated
            variants stay out of default held-out eval runs.

        Returns
        -------
        FailureAnalysis with clusters, recommendations, and summary.
        """
        failure_buckets: dict[str, int] = eval_results.get("failure_buckets", {})
        failure_samples: list[dict[str, Any]] = eval_results.get("failure_samples", [])
        component_attributions: list[dict[str, Any]] | None = eval_results.get(
            "component_attributions"
        )

        # No failures? Return an empty analysis.
        if not any(v > 0 for v in failure_buckets.values()):
            return FailureAnalysis(summary="No failures detected in eval results.")

        # Try LLM-driven analysis first.
        analysis: FailureAnalysis | None = None
        if self.llm_router is not None:
            try:
                analysis = self._llm_analyze(
                    agent_card_markdown=agent_card_markdown,
                    failure_samples=failure_samples,
                    failure_buckets=failure_buckets,
                    component_attributions=component_attributions,
                    past_attempts=past_attempts,
                )
            except Exception:
                logger.warning(
                    "LLM failure analysis failed; falling back to deterministic analysis.",
                    exc_info=True,
                )

        if analysis is None:
            analysis = _deterministic_analysis(failure_buckets, failure_samples)

        # Optional failure-driven variant persistence (R5 C.6).
        if case_generator is not None:
            try:
                self.persist_variants(
                    analysis,
                    case_generator=case_generator,
                    min_cluster_size=min_cluster_size,
                    generated_cases_path=generated_cases_path,
                )
            except Exception:
                logger.warning(
                    "Failure-cluster variant persistence failed; "
                    "continuing without writing generated cases.",
                    exc_info=True,
                )

        return analysis

    # ------------------------------------------------------------------
    # R5 C.6 — persist variants derived from failure clusters
    # ------------------------------------------------------------------

    @staticmethod
    def persist_variants(
        analysis: FailureAnalysis,
        *,
        case_generator: "CardCaseGenerator",
        min_cluster_size: int = 3,
        generated_cases_path: str | Path = DEFAULT_GENERATED_FAILURE_CASES_PATH,
    ) -> list[str]:
        """Write variant cases for each large cluster into the YAML catalog.

        For every cluster in ``analysis.clusters`` with size ``>= min_cluster_size``,
        calls ``case_generator.generate_variants_from_cluster(cluster)`` and
        appends the variants (as YAML case dicts tagged
        ``generated_from:failure_cluster:<cluster_id>``) to
        ``generated_cases_path``. The append is idempotent: variants whose ids
        already exist in the file are skipped. Existing cases are preserved.
        Creates the file (with ``{cases: [...]}`` shape) when missing.

        Returns the list of variant ids that were newly appended.
        """
        path = Path(generated_cases_path)

        # Collect eligible clusters first so we don't touch the filesystem
        # when everything is filtered out.
        eligible = [c for c in analysis.clusters if _cluster_size(c) >= min_cluster_size]
        if not eligible:
            return []

        # Load existing cases (if any).
        existing_cases: list[dict[str, Any]] = []
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            if raw.strip():
                data = yaml.safe_load(raw) or {}
                if isinstance(data, dict) and isinstance(data.get("cases"), list):
                    existing_cases = [
                        dict(entry) for entry in data["cases"] if isinstance(entry, dict)
                    ]

        seen_ids: set[str] = {
            str(case.get("id"))
            for case in existing_cases
            if isinstance(case.get("id"), str)
        }

        new_ids: list[str] = []
        for cluster in eligible:
            variants = case_generator.generate_variants_from_cluster(cluster)
            cluster_id = getattr(cluster, "cluster_id", None) or getattr(
                cluster, "id", "unknown"
            )
            tag = f"generated_from:failure_cluster:{cluster_id}"
            for variant in variants:
                if variant.id in seen_ids:
                    continue
                case_dict = variant.to_dict()
                existing_tags = case_dict.get("tags", [])
                if not isinstance(existing_tags, list):
                    existing_tags = []
                normalized_tags = [str(existing_tag) for existing_tag in existing_tags]
                if tag not in normalized_tags:
                    normalized_tags.append(tag)
                case_dict["tags"] = normalized_tags
                case_dict["split"] = str(case_dict.get("split") or "train")
                existing_cases.append(case_dict)
                seen_ids.add(variant.id)
                new_ids.append(variant.id)

        if not new_ids and path.exists():
            # Nothing to write; preserve file as-is.
            return []

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({"cases": existing_cases}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return new_ids

    def _llm_analyze(
        self,
        agent_card_markdown: str,
        failure_samples: list[dict[str, Any]],
        failure_buckets: dict[str, int],
        component_attributions: list[dict[str, Any]] | None,
        past_attempts: list[dict[str, Any]] | None,
    ) -> FailureAnalysis:
        """Use the LLM router for deep failure analysis."""
        assert self.llm_router is not None

        user_prompt = _build_user_prompt(
            agent_card_markdown=agent_card_markdown,
            failure_samples=failure_samples,
            failure_buckets=failure_buckets,
            component_attributions=component_attributions,
            past_attempts=past_attempts,
        )

        request = LLMRequest(
            system=_SYSTEM_PROMPT,
            prompt=user_prompt,
            temperature=0.2,
            max_tokens=2000,
            metadata={"purpose": "failure_analysis"},
        )

        response = self.llm_router.generate(request)
        payload = _extract_json_payload(response.text)

        if payload is None:
            raise ValueError("LLM returned unparseable response for failure analysis")

        known_sample_ids = {
            str(sample.get("id", sample.get("sample_id", "")))
            for sample in failure_samples
            if str(sample.get("id", sample.get("sample_id", ""))).strip()
        }
        return _parse_llm_analysis(payload, known_sample_ids=known_sample_ids)
