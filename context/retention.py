"""Retention policy management — compliance, anonymization, and expiry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, returning UTC datetime."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)),
    ("phone", re.compile(r"\b(?:\+?\d[\d\s\-().]{7,}\d)\b")),
    ("ip_address", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ \-]?){13,16}\b")),
]


def _redact_str(value: str) -> str:
    """Replace PII patterns in a string with a [REDACTED] placeholder."""
    for label, pattern in _PII_PATTERNS:
        value = pattern.sub(f"[REDACTED_{label.upper()}]", value)
    return value


def _anonymize_value(value: Any) -> Any:
    """Recursively anonymize PII in a value."""
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: _anonymize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_anonymize_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    scope: str
    max_age_days: int
    anonymize_pii: bool = True
    hard_delete: bool = False

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "max_age_days": self.max_age_days,
            "anonymize_pii": self.anonymize_pii,
            "hard_delete": self.hard_delete,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RetentionPolicy":
        return cls(
            scope=d["scope"],
            max_age_days=d["max_age_days"],
            anonymize_pii=d.get("anonymize_pii", True),
            hard_delete=d.get("hard_delete", False),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class RetentionManager:
    """Applies retention policies to collections of entry dicts."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_policies(
        self,
        policies: list[RetentionPolicy],
        entries: list[dict],
    ) -> dict:
        """Apply all matching policies to entries and return stats.

        Stats dict keys:
          - total: int
          - deleted: int
          - anonymized: int
          - kept: int
          - processed_by_scope: dict[scope, int]
        """
        stats: dict = {
            "total": len(entries),
            "deleted": 0,
            "anonymized": 0,
            "kept": 0,
            "processed_by_scope": {},
        }

        policy_map: dict[str, RetentionPolicy] = {p.scope: p for p in policies}
        now = _now_utc()
        surviving: list[dict] = []

        for entry in entries:
            scope = entry.get("scope", "")
            policy = policy_map.get(scope) or policy_map.get("*")
            if policy is None:
                surviving.append(entry)
                stats["kept"] += 1
                continue

            stats["processed_by_scope"][scope] = (
                stats["processed_by_scope"].get(scope, 0) + 1
            )

            created_raw = entry.get("created_at", "")
            created_dt = _parse_iso(created_raw) if created_raw else now
            age_days = (now - created_dt).total_seconds() / 86400

            if age_days > policy.max_age_days:
                if policy.hard_delete:
                    stats["deleted"] += 1
                    continue  # drop entirely
                else:
                    # Soft-delete: anonymize and keep
                    entry = self.anonymize_entry(entry)
                    stats["anonymized"] += 1
            elif policy.anonymize_pii:
                entry = self.anonymize_entry(entry)
                stats["anonymized"] += 1
            else:
                stats["kept"] += 1

            surviving.append(entry)

        # Replace in-place
        entries[:] = surviving
        return stats

    def anonymize_entry(self, entry: dict) -> dict:
        """Return a copy of entry with PII fields anonymized."""
        result: dict = {}
        for k, v in entry.items():
            result[k] = _anonymize_value(v)
        return result

    def check_compliance(
        self,
        entries: list[dict],
        policies: list[RetentionPolicy],
    ) -> list[str]:
        """Return a list of violation strings for entries that breach policies.

        Does NOT mutate entries.
        """
        policy_map: dict[str, RetentionPolicy] = {p.scope: p for p in policies}
        now = _now_utc()
        violations: list[str] = []

        for entry in entries:
            scope = entry.get("scope", "")
            policy = policy_map.get(scope) or policy_map.get("*")
            if policy is None:
                continue

            created_raw = entry.get("created_at", "")
            created_dt = _parse_iso(created_raw) if created_raw else now
            age_days = (now - created_dt).total_seconds() / 86400

            if age_days > policy.max_age_days:
                key = entry.get("key", "<unknown>")
                violations.append(
                    f"Entry '{key}' in scope '{scope}' exceeds max_age_days "
                    f"({age_days:.1f} > {policy.max_age_days})"
                )

        return violations
