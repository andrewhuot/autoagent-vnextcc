"""Rule-based judge — configurable format and field-presence checks.

All verdicts have confidence=1.0 since rules are deterministic.
"""

from __future__ import annotations

from typing import Any

from core.types import JudgeVerdict


class RuleBasedJudge:
    """Configurable rule-based evaluation for format and field constraints."""

    JUDGE_ID = "rule_based"

    def check_format(self, text: str, rules: dict[str, Any]) -> JudgeVerdict:
        """Check *text* against a set of format rules.

        Supported rules (all optional):
            required_fields: list[str] — substrings that must appear in text
            max_length: int — text must not exceed this character count
            min_length: int — text must be at least this long
            banned_words: list[str] — substrings that must NOT appear in text
        """
        failures: list[str] = []
        evidence: list[str] = []
        checks_run = 0

        # --- required_fields ---
        required_fields: list[str] = rules.get("required_fields", [])
        for field in required_fields:
            checks_run += 1
            if field.lower() in text.lower():
                evidence.append(f"contains '{field}'")
            else:
                failures.append(f"Missing required field: '{field}'")

        # --- max_length ---
        max_length: int | None = rules.get("max_length")
        if max_length is not None:
            checks_run += 1
            if len(text) <= max_length:
                evidence.append(f"length {len(text)} <= {max_length}")
            else:
                failures.append(f"Text length {len(text)} exceeds max_length {max_length}")

        # --- min_length ---
        min_length: int | None = rules.get("min_length")
        if min_length is not None:
            checks_run += 1
            if len(text) >= min_length:
                evidence.append(f"length {len(text)} >= {min_length}")
            else:
                failures.append(f"Text length {len(text)} below min_length {min_length}")

        # --- banned_words ---
        banned_words: list[str] = rules.get("banned_words", [])
        for word in banned_words:
            checks_run += 1
            if word.lower() in text.lower():
                failures.append(f"Banned word found: '{word}'")
            else:
                evidence.append(f"no banned word '{word}'")

        total = max(checks_run, 1)
        passed_checks = total - len(failures)
        score = passed_checks / total

        return JudgeVerdict(
            score=score,
            passed=len(failures) == 0,
            judge_id=self.JUDGE_ID,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=1.0,
            metadata={"check": "format", "rules": rules, "checks_run": checks_run},
        )

    def check_required_fields(
        self, data: dict[str, Any], required: list[str]
    ) -> JudgeVerdict:
        """Check that all *required* keys exist in *data*.

        Missing keys are reported as failures; present keys appear in evidence.
        """
        failures: list[str] = []
        evidence: list[str] = []

        for field in required:
            if field in data:
                evidence.append(f"field '{field}' present")
            else:
                failures.append(f"Missing required field: '{field}'")

        total = max(len(required), 1)
        score = len(evidence) / total

        return JudgeVerdict(
            score=score,
            passed=len(failures) == 0,
            judge_id=self.JUDGE_ID,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=1.0,
            metadata={"check": "required_fields", "required": required},
        )
