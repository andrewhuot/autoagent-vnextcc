"""PII scanning and redaction for trace ingestion.

Conservative regex-based detection for common PII patterns. Redaction is
one-way (non-reversible) and idempotent — ``redact(redact(t)) == redact(t)``.

The scanner is intentionally tuned for **low false-negative rate**. False
positives (e.g. matching ``999.999.999.999`` as an IPv4 address) are
acceptable; false negatives — real PII leaking through — are not.

Plan reference: R5 §1.8 (trace ingestion) and §4 invariant 5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class PIIKind(str, Enum):
    """Kinds of PII the scanner recognises."""

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CREDIT_CARD = "CREDIT_CARD"
    BEARER_TOKEN = "BEARER_TOKEN"
    IPV4 = "IPV4"
    USER_PATH = "USER_PATH"  # /home/<user> or /Users/<user>


@dataclass(frozen=True)
class Hit:
    """One match produced by :func:`scan`.

    ``matched`` is the raw substring; callers use it to print redaction
    summaries without re-slicing ``text``.
    """

    kind: PIIKind
    start: int
    end: int
    matched: str


# Compiled patterns. Order here is not load-bearing — non-overlap is enforced
# after combining all hits. Patterns are conservative by design: we prefer
# false positives over false negatives so that PII never leaks silently.
_PATTERNS: list[tuple[PIIKind, re.Pattern[str]]] = [
    (PIIKind.EMAIL, re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    (
        PIIKind.PHONE,
        # North-American formats: optional country code, optional paren area
        # code, common separators. Does not attempt to match all international
        # phone formats — documented limitation.
        re.compile(
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
    ),
    (
        PIIKind.CREDIT_CARD,
        # 16-digit groups with optional spaces or dashes. We intentionally
        # skip the Luhn check: test card numbers should also be redacted.
        re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ),
    (
        PIIKind.BEARER_TOKEN,
        # Bearer <token>, api_key=..., api-key: ..., and OpenAI-style sk-...
        re.compile(
            r"(?i)\b(?:bearer\s+|api[_-]?key[:=]\s*|sk-[a-zA-Z0-9]{20,})"
            r"[A-Za-z0-9_\-\.]{10,}"
        ),
    ),
    (
        PIIKind.IPV4,
        # We do not validate octet range — 999.999.999.999 matches and is an
        # acceptable false positive (the goal is redaction, not validation).
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ),
    (
        PIIKind.USER_PATH,
        # /home/alice or /Users/bob, plus any path segment up to the next
        # path separator, whitespace, or colon.
        re.compile(r"/(?:home|Users)/[^\s/:]+"),
    ),
]


def scan(text: str) -> list[Hit]:
    """Return all PII hits in *text*, sorted by ``start`` offset.

    When patterns overlap (e.g. an email embedded inside a user path), a
    greedy non-overlap rule applies: hits are sorted by ``(start, -length)``
    and any hit starting inside a previously accepted hit's span is dropped.
    This means the longest-or-earliest span wins.

    Returns an empty list for empty input.
    """
    if not text:
        return []

    raw: list[Hit] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            raw.append(
                Hit(
                    kind=kind,
                    start=m.start(),
                    end=m.end(),
                    matched=m.group(0),
                )
            )

    # Greedy non-overlap: sort by (start asc, length desc) so longer spans
    # win ties, then accept hits that don't overlap the last accepted hit.
    raw.sort(key=lambda h: (h.start, -(h.end - h.start)))
    accepted: list[Hit] = []
    last_end = -1
    for hit in raw:
        if hit.start >= last_end:
            accepted.append(hit)
            last_end = hit.end
    # Already sorted by start.
    return accepted


def redact(text: str, hits: list[Hit] | None = None) -> str:
    """Return *text* with each hit replaced by ``<REDACTED:KIND>``.

    Passing ``hits=None`` scans *text* first. Redaction is non-reversible
    and idempotent: ``redact(redact(t)) == redact(t)``.
    """
    if hits is None:
        hits = scan(text)
    if not hits:
        return text

    # Replace right-to-left so earlier offsets stay valid.
    out = text
    for hit in sorted(hits, key=lambda h: h.start, reverse=True):
        replacement = f"<REDACTED:{hit.kind.value}>"
        out = out[: hit.start] + replacement + out[hit.end :]
    return out


def scan_case(case: dict) -> dict[PIIKind, int]:
    """Scan all string fields of *case*. Return a count per :class:`PIIKind`.

    Non-string fields (lists, dicts, numbers, bools, ``None``) are skipped —
    the CLI applies :func:`redact` field-by-field later, and we want the
    pre-redaction summary to match exactly what gets rewritten.
    """
    counts: dict[PIIKind, int] = {}
    for value in case.values():
        if not isinstance(value, str):
            continue
        for hit in scan(value):
            counts[hit.kind] = counts.get(hit.kind, 0) + 1
    return counts
