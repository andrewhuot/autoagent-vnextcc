"""NL-to-scorer compilation engine.

Compiles natural language criteria descriptions into structured
ScorerDimension lists using deterministic regex pattern matching.
No LLM calls required — fully testable and reproducible.
"""

from __future__ import annotations

import re
from typing import Any

from evals.scorer_spec import ScorerDimension


# ---------------------------------------------------------------------------
# Pattern matching for common criteria types
# ---------------------------------------------------------------------------

# Each tuple: (compiled_regex, grader_type, default_config)
CRITERIA_PATTERNS: list[tuple[re.Pattern[str], str, dict[str, Any]]] = [
    # Latency/speed patterns -> deterministic threshold
    (
        re.compile(
            r"(?:respond|response|reply|answer).*?"
            r"(?:under|within|less than|faster than|below)\s*"
            r"(\d+)\s*(?:s|sec|seconds|ms|milliseconds)",
            re.IGNORECASE,
        ),
        "deterministic",
        {"type": "latency_threshold"},
    ),
    # Time patterns with "under X seconds"
    (
        re.compile(
            r"(?:under|within|less than)\s*(\d+)\s*(?:s|sec|seconds)",
            re.IGNORECASE,
        ),
        "deterministic",
        {"type": "latency_threshold"},
    ),
    # Safety/hallucination -> llm_judge
    (
        re.compile(
            r"(?:not?|don.?t|never|avoid|must not)\s*"
            r"(?:make up|fabricat|hallucinate|invent|lie|false)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "hallucination_check"},
    ),
    # Tool usage (must come before accuracy to avoid "right" matching accuracy)
    (
        re.compile(
            r"(?:use.*(?:right|correct|appropriate).*tool|"
            r"tool.*(?:usage|use|selection)|right\s+tool)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "tool_usage_check"},
    ),
    # Accuracy/correctness -> llm_judge
    (
        re.compile(
            r"(?:accurat|correct|proper|factual|true|ground)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "accuracy_check"},
    ),
    # Tone/style -> llm_judge
    (
        re.compile(
            r"(?:professional|friendly|polite|formal|casual|empathetic|"
            r"warm|tone|style|manner)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "tone_check"},
    ),
    # Completeness -> llm_judge
    (
        re.compile(
            r"(?:complet|thorough|full|comprehensive|address all|cover)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "completeness_check"},
    ),
    # First contact resolution
    (
        re.compile(
            r"(?:first contact|first try|single interaction|"
            r"one interaction|resolv.*first)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "resolution_check"},
    ),
    # Follow-up/helpfulness
    (
        re.compile(
            r"(?:offer.*help|follow.?up|additional.*assist|"
            r"anything else|further help)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "followup_check"},
    ),
    # Repetition avoidance
    (
        re.compile(
            r"(?:not.*repeat|don.?t.*ask.*again|avoid.*repeat|"
            r"not.*ask.*same)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "repetition_check"},
    ),
    # PII / privacy
    (
        re.compile(
            r"(?:never.*share.*pii|no.*pii|pii|personal.*information|"
            r"privacy|confidential)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "privacy_check"},
    ),
    # Citation / sourcing
    (
        re.compile(
            r"(?:cite|source|reference|attribution)",
            re.IGNORECASE,
        ),
        "llm_judge",
        {"type": "citation_check"},
    ),
]

# Words to strip when generating dimension names
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "and", "but", "or", "nor", "not", "so",
    "yet", "both", "either", "neither", "each", "every", "all", "any",
    "few", "more", "most", "other", "some", "such", "no", "only", "own",
    "same", "than", "too", "very", "just", "don", "dont", "t", "s",
    "it", "its", "that", "this", "these", "those", "agent", "should",
    "always", "never", "make", "up",
})


class NLCompiler:
    """Compiles natural language criteria into structured scorer dimensions."""

    def compile(self, nl_description: str) -> list[ScorerDimension]:
        """Parse NL description into structured dimensions.

        Strategy:
        1. Split into individual criteria
        2. Pattern-match each criterion
        3. Fall back to LLM judge for unmatched criteria
        4. Assign weights and classify layers
        """
        criteria = self._split_criteria(nl_description)
        if not criteria:
            return []

        total = len(criteria)
        dimensions: list[ScorerDimension] = []
        for i, criterion in enumerate(criteria):
            dim = self._create_dimension(criterion, i, total)
            dimensions.append(dim)

        dimensions = self._assign_weights(dimensions)
        return dimensions

    def _split_criteria(self, text: str) -> list[str]:
        """Split NL text into individual criteria."""
        text = text.strip()
        if not text:
            return []

        # First split by newlines and bullet points
        lines: list[str] = []
        for line in re.split(r"\n+", text):
            line = re.sub(r"^[\s\-\*\d+\.]+", "", line).strip()
            if line:
                lines.append(line)

        # If we only got one line, try splitting by comma/semicolon and 'and'
        if len(lines) == 1:
            line = lines[0]
            # Split on period-separated sentences first (e.g. "Safety: no PII. Quality: cite sources.")
            parts = re.split(r"\.\s+", line)
            parts = [p.strip().rstrip(".") for p in parts if p.strip().rstrip(".")]
            if len(parts) > 1:
                return parts
            # Split on semicolons
            parts = re.split(r"\s*;\s*", line)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]
            # Split on commas (but not commas inside parentheses)
            parts = re.split(r",\s*(?:and\s+)?", line)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]
            # Split on standalone 'and' (word boundary)
            parts = re.split(r"\s+and\s+", line)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]
            # Single criterion
            return [line]

        # Multiple lines — further split each line by period-separated sentences
        result: list[str] = []
        for line in lines:
            # Split on ". " but not on decimal numbers
            sentences = re.split(r"\.\s+", line)
            for s in sentences:
                s = s.strip().rstrip(".")
                if s:
                    result.append(s)
        return result

    def _match_pattern(
        self, criterion: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Try to match a criterion against known patterns.

        Returns (dimension_name, grader_type, grader_config) or None.
        """
        for pattern, grader_type, default_config in CRITERIA_PATTERNS:
            match = pattern.search(criterion)
            if match:
                name = self._generate_dimension_name(criterion)
                config = self._build_grader_config(
                    grader_type, default_config, criterion, match
                )
                return (name, grader_type, config)
        return None

    def _create_dimension(
        self, criterion: str, index: int, total: int
    ) -> ScorerDimension:
        """Create a ScorerDimension from a single criterion."""
        matched = self._match_pattern(criterion)

        if matched:
            name, grader_type, config = matched
        else:
            # Fallback: LLM judge with the criterion as rubric
            name = self._generate_dimension_name(criterion)
            grader_type = "llm_judge"
            config = {
                "type": "custom_check",
                "rubric": criterion,
            }

        layer = self._classify_layer(grader_type, config)
        required = layer == "hard_gate"

        return ScorerDimension(
            name=name,
            description=criterion,
            grader_type=grader_type,
            grader_config=config,
            weight=1.0,  # placeholder — _assign_weights normalises later
            layer=layer,
            required=required,
        )

    def _assign_weights(
        self, dimensions: list[ScorerDimension]
    ) -> list[ScorerDimension]:
        """Assign weights: hard_gate dimensions get higher weight, all sum to ~1.0."""
        if not dimensions:
            return dimensions

        # Base weight per dimension
        raw_weights: list[float] = []
        for dim in dimensions:
            if dim.layer == "hard_gate":
                raw_weights.append(2.0)
            elif dim.layer == "outcome":
                raw_weights.append(1.5)
            elif dim.layer == "slo":
                raw_weights.append(1.0)
            else:
                raw_weights.append(0.5)

        total_raw = sum(raw_weights)
        if total_raw == 0:
            return dimensions

        for i, dim in enumerate(dimensions):
            dim.weight = round(raw_weights[i] / total_raw, 4)

        return dimensions

    def _classify_layer(self, grader_type: str, config: dict[str, Any]) -> str:
        """Classify dimension into MetricLayer."""
        check_type = config.get("type", "")

        # Deterministic latency checks are SLOs
        if grader_type == "deterministic" and "latency" in check_type:
            return "slo"

        # Safety-related checks are hard gates
        if check_type in ("hallucination_check", "privacy_check"):
            return "hard_gate"

        # Quality/accuracy/completeness/tone are outcome metrics
        if check_type in (
            "accuracy_check",
            "completeness_check",
            "tone_check",
            "resolution_check",
            "citation_check",
        ):
            return "outcome"

        # Everything else is diagnostic
        return "diagnostic"

    def _generate_dimension_name(self, criterion: str) -> str:
        """Generate a snake_case name from the criterion text."""
        # Lowercase and strip punctuation
        text = criterion.lower()
        text = re.sub(r"[^a-z0-9\s]", "", text)

        words = [w for w in text.split() if w not in _STOP_WORDS and len(w) > 1]

        # Take first 4 meaningful words
        name_parts = words[:4]
        if not name_parts:
            name_parts = ["criterion"]

        return "_".join(name_parts)

    def _build_grader_config(
        self,
        grader_type: str,
        pattern_config: dict[str, Any],
        criterion: str,
        match: re.Match[str],
    ) -> dict[str, Any]:
        """Build the grader config for a dimension."""
        config: dict[str, Any] = dict(pattern_config)

        if grader_type == "deterministic":
            # Extract numeric threshold from the match
            groups = match.groups()
            if groups:
                threshold_str = groups[0]
                threshold = float(threshold_str)
                # Detect if milliseconds or seconds
                if "ms" in criterion.lower() or "millisecond" in criterion.lower():
                    config["threshold_ms"] = threshold
                else:
                    # Assume seconds, convert to ms
                    config["threshold_ms"] = threshold * 1000
                config["operator"] = "lte"  # latency must be <= threshold

        elif grader_type == "llm_judge":
            # Build rubric from the criterion
            config["rubric"] = criterion

        elif grader_type == "similarity":
            config["rubric"] = criterion

        return config
