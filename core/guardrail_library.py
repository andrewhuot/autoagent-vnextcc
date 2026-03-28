"""Pre-built guardrails for AutoAgent VNextCC (P1-3).

Each guardrail is a concrete subclass of ``Guardrail`` that can be registered
with a ``GuardrailRegistry`` and composed into ``GuardrailChain`` instances.

All pattern matching is done with simple regex + keyword lists so there are
no external ML dependencies — these are fast, deterministic, and auditable.
"""
from __future__ import annotations

import json
import re
from typing import Any

from core.guardrails import (
    Guardrail,
    GuardrailRegistry,
    GuardrailResult,
    GuardrailSeverity,
    GuardrailType,
)


# ---------------------------------------------------------------------------
# PiiDetectionGuardrail
# ---------------------------------------------------------------------------

# Patterns for common PII types
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone_us": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6011\d{12})\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


class PiiDetectionGuardrail(Guardrail):
    """Detects common PII patterns (email, phone, SSN, credit card, IP).

    Can be configured to check inputs, outputs, or both.
    """

    def __init__(
        self,
        severity: GuardrailSeverity = GuardrailSeverity.BLOCK,
        guardrail_type: GuardrailType = GuardrailType.BOTH,
        enabled: bool = True,
        extra_patterns: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            name="pii_detection",
            description="Detects common PII: email, phone, SSN, credit card, IP address.",
            guardrail_type=guardrail_type,
            severity=severity,
            enabled=enabled,
        )
        self._patterns = dict(_PII_PATTERNS)
        if extra_patterns:
            for k, v in extra_patterns.items():
                self._patterns[k] = re.compile(v)

    def _check(self, text: str, direction: str) -> GuardrailResult:
        found: dict[str, list[str]] = {}
        for pii_type, pattern in self._patterns.items():
            matches = pattern.findall(text)
            if matches:
                # Redact match values for safety
                found[pii_type] = [f"<{pii_type}_redacted>" for _ in matches]

        if found:
            types_found = ", ".join(found.keys())
            return GuardrailResult(
                passed=False,
                severity=self.severity,
                message=f"PII detected in {direction}: {types_found}",
                guardrail_name=self.name,
                metadata={"pii_types": list(found.keys()), "direction": direction},
            )
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message=f"No PII detected in {direction}.",
            guardrail_name=self.name,
        )

    def validate_input(self, input_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(input_text, "input")

    def validate_output(self, output_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(output_text, "output")

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["extra_patterns"] = {k: p.pattern for k, p in self._patterns.items() if k not in _PII_PATTERNS}
        return d


# ---------------------------------------------------------------------------
# ToxicityGuardrail
# ---------------------------------------------------------------------------

_DEFAULT_TOXIC_KEYWORDS: list[str] = [
    # Slurs, threats, and extreme content — kept abstract to avoid reproducing
    # actual slurs.  Operators should supply a domain-appropriate list.
    "kill yourself", "kys", "go die", "hate speech placeholder",
    "i will hurt", "i will kill", "bomb threat", "death threat",
]


class ToxicityGuardrail(Guardrail):
    """Keyword-based toxicity detection.

    Checks for a configurable list of toxic phrases.  Operators should
    provide a domain-appropriate keyword list via ``toxic_keywords``.
    """

    def __init__(
        self,
        toxic_keywords: list[str] | None = None,
        severity: GuardrailSeverity = GuardrailSeverity.BLOCK,
        guardrail_type: GuardrailType = GuardrailType.BOTH,
        enabled: bool = True,
        case_sensitive: bool = False,
    ) -> None:
        super().__init__(
            name="toxicity",
            description="Keyword-based toxicity detection for harmful or threatening language.",
            guardrail_type=guardrail_type,
            severity=severity,
            enabled=enabled,
        )
        self._keywords = toxic_keywords if toxic_keywords is not None else list(_DEFAULT_TOXIC_KEYWORDS)
        self._case_sensitive = case_sensitive

    def _check(self, text: str, direction: str) -> GuardrailResult:
        check_text = text if self._case_sensitive else text.lower()
        triggered = [
            kw for kw in self._keywords
            if (kw if self._case_sensitive else kw.lower()) in check_text
        ]
        if triggered:
            return GuardrailResult(
                passed=False,
                severity=self.severity,
                message=f"Toxicity detected in {direction}: {len(triggered)} keyword(s) matched.",
                guardrail_name=self.name,
                metadata={"matched_keywords": triggered, "direction": direction},
            )
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message=f"No toxicity detected in {direction}.",
            guardrail_name=self.name,
        )

    def validate_input(self, input_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(input_text, "input")

    def validate_output(self, output_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(output_text, "output")

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["toxic_keywords_count"] = len(self._keywords)
        d["case_sensitive"] = self._case_sensitive
        return d


# ---------------------------------------------------------------------------
# TopicRestrictionGuardrail
# ---------------------------------------------------------------------------

class TopicRestrictionGuardrail(Guardrail):
    """Block requests or responses about restricted topics.

    Topics are matched via substring or regex patterns.  The list of
    restricted topics is operator-configurable.
    """

    def __init__(
        self,
        restricted_topics: list[str] | None = None,
        severity: GuardrailSeverity = GuardrailSeverity.BLOCK,
        guardrail_type: GuardrailType = GuardrailType.BOTH,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="topic_restriction",
            description="Blocks requests/responses about operator-configured restricted topics.",
            guardrail_type=guardrail_type,
            severity=severity,
            enabled=enabled,
        )
        self._topics = restricted_topics or []
        self._patterns = [re.compile(re.escape(t), re.IGNORECASE) for t in self._topics]

    def _check(self, text: str, direction: str) -> GuardrailResult:
        matched = [
            topic for topic, pattern in zip(self._topics, self._patterns)
            if pattern.search(text)
        ]
        if matched:
            return GuardrailResult(
                passed=False,
                severity=self.severity,
                message=f"Restricted topic detected in {direction}: {', '.join(matched)}",
                guardrail_name=self.name,
                metadata={"matched_topics": matched, "direction": direction},
            )
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message=f"No restricted topics in {direction}.",
            guardrail_name=self.name,
        )

    def validate_input(self, input_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(input_text, "input")

    def validate_output(self, output_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        return self._check(output_text, "output")

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["restricted_topics"] = self._topics
        return d


# ---------------------------------------------------------------------------
# OutputFormatGuardrail
# ---------------------------------------------------------------------------

class OutputFormatGuardrail(Guardrail):
    """Validate that outputs conform to an expected format.

    Supports:
    - ``json``: output must be valid JSON
    - ``max_length``: output must not exceed ``max_length`` characters
    - ``min_length``: output must be at least ``min_length`` characters
    - ``regex``: output must match the given regex pattern
    """

    def __init__(
        self,
        expected_format: str = "json",
        max_length: int | None = None,
        min_length: int | None = None,
        regex_pattern: str | None = None,
        severity: GuardrailSeverity = GuardrailSeverity.WARN,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="output_format",
            description=(
                f"Validates output format: expected={expected_format}, "
                f"max_length={max_length}, min_length={min_length}."
            ),
            guardrail_type=GuardrailType.OUTPUT_VALIDATION,
            severity=severity,
            enabled=enabled,
        )
        self._expected_format = expected_format
        self._max_length = max_length
        self._min_length = min_length
        self._regex: re.Pattern[str] | None = re.compile(regex_pattern) if regex_pattern else None

    def validate_output(self, output_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        violations: list[str] = []

        # Length checks
        if self._max_length is not None and len(output_text) > self._max_length:
            violations.append(
                f"Output length {len(output_text)} exceeds max {self._max_length}"
            )
        if self._min_length is not None and len(output_text) < self._min_length:
            violations.append(
                f"Output length {len(output_text)} is below min {self._min_length}"
            )

        # Format checks
        if self._expected_format == "json":
            try:
                json.loads(output_text)
            except (json.JSONDecodeError, ValueError) as exc:
                violations.append(f"Output is not valid JSON: {exc}")

        # Regex check
        if self._regex and not self._regex.search(output_text):
            violations.append(f"Output does not match required pattern: {self._regex.pattern}")

        if violations:
            return GuardrailResult(
                passed=False,
                severity=self.severity,
                message="Output format violations: " + "; ".join(violations),
                guardrail_name=self.name,
                metadata={"violations": violations, "format": self._expected_format},
            )
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message="Output format is valid.",
            guardrail_name=self.name,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "expected_format": self._expected_format,
            "max_length": self._max_length,
            "min_length": self._min_length,
            "regex_pattern": self._regex.pattern if self._regex else None,
        })
        return d


# ---------------------------------------------------------------------------
# PromptInjectionGuardrail
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Classic "ignore previous instructions"
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context)", re.IGNORECASE),
    # "forget everything"
    re.compile(r"forget\s+(everything|all|prior|previous)", re.IGNORECASE),
    # Jailbreak role-play triggers
    re.compile(r"you\s+are\s+now\s+(DAN|jailbreak|unrestricted|evil|hacked)", re.IGNORECASE),
    re.compile(r"(act|pretend|behave)\s+as\s+(if\s+)?(you\s+are\s+)?(DAN|evil|hacked|unrestricted)", re.IGNORECASE),
    # System prompt leakage attempts
    re.compile(r"(print|output|reveal|show|display|repeat)\s+(your\s+)?(system\s+prompt|instructions|prompt)", re.IGNORECASE),
    # "Do anything now"
    re.compile(r"\bDAN\b"),
    # Delimiter injection
    re.compile(r"<\|?(system|endoftext|user|assistant|im_start|im_end)\|?>", re.IGNORECASE),
    # Override commands
    re.compile(r"\/\/(system|override|sudo|root|admin)\b", re.IGNORECASE),
]


class PromptInjectionGuardrail(Guardrail):
    """Detect common prompt injection and jailbreak patterns in inputs."""

    def __init__(
        self,
        severity: GuardrailSeverity = GuardrailSeverity.BLOCK,
        enabled: bool = True,
        extra_patterns: list[str] | None = None,
    ) -> None:
        super().__init__(
            name="prompt_injection",
            description="Detects prompt injection and jailbreak attempts in user inputs.",
            guardrail_type=GuardrailType.INPUT_VALIDATION,
            severity=severity,
            enabled=enabled,
        )
        self._patterns = list(_INJECTION_PATTERNS)
        if extra_patterns:
            self._patterns.extend(re.compile(p, re.IGNORECASE) for p in extra_patterns)

    def validate_input(self, input_text: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        matched: list[str] = []
        for pattern in self._patterns:
            if pattern.search(input_text):
                matched.append(pattern.pattern)

        if matched:
            return GuardrailResult(
                passed=False,
                severity=self.severity,
                message=f"Prompt injection attempt detected: {len(matched)} pattern(s) matched.",
                guardrail_name=self.name,
                metadata={"matched_patterns": matched},
            )
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message="No prompt injection detected.",
            guardrail_name=self.name,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["builtin_pattern_count"] = len(_INJECTION_PATTERNS)
        d["total_pattern_count"] = len(self._patterns)
        return d


# ---------------------------------------------------------------------------
# Registry factory
# ---------------------------------------------------------------------------

def register_default_guardrails(registry: GuardrailRegistry) -> None:
    """Register all built-in guardrails into *registry*.

    Default severities:
    - PII detection   → BLOCK
    - Toxicity        → BLOCK
    - Topic restriction (empty list) → WARN
    - Output format   → WARN (JSON, no length limits by default)
    - Prompt injection → BLOCK
    """
    registry.register(PiiDetectionGuardrail(severity=GuardrailSeverity.BLOCK))
    registry.register(ToxicityGuardrail(severity=GuardrailSeverity.BLOCK))
    registry.register(
        TopicRestrictionGuardrail(
            restricted_topics=[],  # Operator must populate
            severity=GuardrailSeverity.WARN,
        )
    )
    registry.register(
        OutputFormatGuardrail(
            expected_format="text",
            severity=GuardrailSeverity.WARN,
        )
    )
    registry.register(PromptInjectionGuardrail(severity=GuardrailSeverity.BLOCK))
