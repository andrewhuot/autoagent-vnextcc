"""Tests for evals.dataset.redact — PII scanning + redaction."""
from __future__ import annotations

import pytest

from evals.dataset.redact import Hit, PIIKind, redact, scan, scan_case


def test_scan_empty_text() -> None:
    assert scan("") == []


def test_scan_no_pii() -> None:
    assert scan("no pii here, just words") == []


def test_scan_email_single() -> None:
    hits = scan("contact alice@example.com today")
    assert len(hits) == 1
    assert hits[0].kind is PIIKind.EMAIL
    assert hits[0].matched == "alice@example.com"


def test_scan_email_multiple() -> None:
    text = "mail a@b.io and c+tag@d.co.uk please"
    hits = scan(text)
    emails = [h for h in hits if h.kind is PIIKind.EMAIL]
    assert len(emails) == 2
    assert emails[0].start < emails[1].start


def test_scan_phone() -> None:
    hits = scan("call me at 415-555-1234 or (212) 555-9999")
    phones = [h for h in hits if h.kind is PIIKind.PHONE]
    assert len(phones) >= 2


def test_scan_credit_card_with_dashes() -> None:
    hits = scan("card 4111-1111-1111-1111 on file")
    ccs = [h for h in hits if h.kind is PIIKind.CREDIT_CARD]
    assert len(ccs) == 1
    assert ccs[0].matched == "4111-1111-1111-1111"


def test_scan_bearer_token() -> None:
    hits = scan("Authorization: Bearer abcdefghijklmnop1234")
    tokens = [h for h in hits if h.kind is PIIKind.BEARER_TOKEN]
    assert len(tokens) == 1


def test_scan_openai_api_key() -> None:
    key = "sk-" + "A" * 40
    hits = scan(f"key={key} end")
    tokens = [h for h in hits if h.kind is PIIKind.BEARER_TOKEN]
    assert len(tokens) == 1


def test_scan_ipv4() -> None:
    hits = scan("server at 192.168.1.1 and 10.0.0.5")
    ips = [h for h in hits if h.kind is PIIKind.IPV4]
    assert len(ips) == 2


def test_scan_user_home_path() -> None:
    hits = scan("log at /home/alice/data.txt")
    paths = [h for h in hits if h.kind is PIIKind.USER_PATH]
    assert len(paths) == 1
    assert paths[0].matched.startswith("/home/alice")


def test_scan_macos_user_path() -> None:
    hits = scan("file /Users/bob/docs/foo.md written")
    paths = [h for h in hits if h.kind is PIIKind.USER_PATH]
    assert len(paths) == 1
    assert paths[0].matched.startswith("/Users/bob")


def test_scan_hits_sorted_by_start() -> None:
    text = "ip 10.0.0.1 then alice@x.com and /Users/carol/foo"
    hits = scan(text)
    starts = [h.start for h in hits]
    assert starts == sorted(starts)


def test_scan_overlapping_hits_dropped_nonoverlapping_kept() -> None:
    # Email inside path: /Users/alice@example.com/...
    # The USER_PATH and EMAIL patterns may overlap; greedy non-overlap should
    # keep the first (longer/earlier) and drop the overlapping one.
    text = "path /Users/alice/logs and email bob@example.com"
    hits = scan(text)
    # Verify non-overlap: sort by start, check each starts after the previous end
    for a, b in zip(hits, hits[1:]):
        assert b.start >= a.end, f"overlap: {a} and {b}"


def test_redact_replaces_with_kind_marker() -> None:
    out = redact("email me at alice@example.com now")
    assert "<REDACTED:EMAIL>" in out
    assert "alice@example.com" not in out


def test_redact_none_hits_runs_scan() -> None:
    text = "ip 10.0.0.1 here"
    assert redact(text, None) == redact(text, scan(text))


def test_redact_idempotent() -> None:
    text = "email a@b.io and ip 1.2.3.4 at /home/x/y"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_preserves_non_pii() -> None:
    text = "no pii here at all, just words"
    assert redact(text) == text


def test_scan_case_counts_per_kind() -> None:
    case = {
        "user_message": "write to alice@example.com please",
        "reference_answer": "server 10.0.0.1 is down",
        "category": "ops",
    }
    counts = scan_case(case)
    assert counts[PIIKind.EMAIL] == 1
    assert counts[PIIKind.IPV4] == 1


def test_scan_case_skips_non_string_fields() -> None:
    case = {
        "user_message": "contact a@b.io",
        "expected_keywords": ["foo", "bar"],  # list
        "metadata": {"nested": "c@d.io"},      # dict
        "safety_probe": False,                  # bool
        "count": 3,                             # int
    }
    # Should not crash and should count the one email in user_message.
    counts = scan_case(case)
    assert counts.get(PIIKind.EMAIL, 0) == 1


def test_hit_is_frozen_dataclass() -> None:
    h = Hit(kind=PIIKind.EMAIL, start=0, end=5, matched="a@b.c")
    with pytest.raises(Exception):
        h.start = 99  # type: ignore[misc]
