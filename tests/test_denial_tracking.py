"""Tests for cli.permissions.denial_tracking.DenialTracker.

Judgment call: an empty-string tool name is *accepted* by the tracker
(stored under the ``""`` key). See class docstring for the rationale —
the tracker is honest about what the caller passed rather than silently
dropping the record. The two empty-string tests below pin that behavior
so a future change cannot flip it accidentally.
"""

from __future__ import annotations

import pytest

from cli.permissions.denial_tracking import DenialTracker


def test_counter_starts_at_zero():
    t = DenialTracker(max_per_session_per_tool=3)
    assert t.denial_count("bash") == 0
    assert t.should_escalate_to_prompt("bash") is False


def test_counter_advances_and_fires_at_threshold():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3):
        t.record_denial("bash")
    assert t.denial_count("bash") == 3
    assert t.should_escalate_to_prompt("bash") is True


def test_counter_fires_above_threshold():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(10):
        t.record_denial("bash")
    assert t.denial_count("bash") == 10
    assert t.should_escalate_to_prompt("bash") is True


def test_counter_below_threshold_does_not_fire():
    t = DenialTracker(max_per_session_per_tool=3)
    t.record_denial("bash")
    t.record_denial("bash")
    assert t.denial_count("bash") == 2
    assert t.should_escalate_to_prompt("bash") is False


def test_per_tool_independence():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3):
        t.record_denial("bash")
    assert t.should_escalate_to_prompt("bash") is True
    assert t.should_escalate_to_prompt("file_read") is False
    assert t.denial_count("file_read") == 0


def test_reset_clears_all_counters():
    t = DenialTracker(max_per_session_per_tool=3)
    for _ in range(3):
        t.record_denial("bash")
    for _ in range(2):
        t.record_denial("file_read")
    t.reset()
    assert t.denial_count("bash") == 0
    assert t.denial_count("file_read") == 0
    assert t.should_escalate_to_prompt("bash") is False


def test_reset_preserves_max():
    t = DenialTracker(max_per_session_per_tool=5)
    t.record_denial("bash")
    t.reset()
    assert t.max_per_session_per_tool == 5


def test_negative_max_raises():
    with pytest.raises(ValueError):
        DenialTracker(max_per_session_per_tool=-1)


def test_zero_max_never_escalates():
    t = DenialTracker(max_per_session_per_tool=0)
    for _ in range(100):
        t.record_denial("bash")
    assert t.denial_count("bash") == 100
    assert t.should_escalate_to_prompt("bash") is False


def test_default_max_is_three():
    t = DenialTracker()
    assert t.max_per_session_per_tool == 3


def test_empty_string_tool_name_is_accepted():
    # Judgment call: empty-string tool names are accepted verbatim, not
    # silently dropped. The classifier gate is responsible for not passing
    # meaningless names; the tracker stays honest about what it receives.
    t = DenialTracker(max_per_session_per_tool=2)
    t.record_denial("")
    assert t.denial_count("") == 1
    t.record_denial("")
    assert t.denial_count("") == 2
    assert t.should_escalate_to_prompt("") is True
    # And other tools remain unaffected.
    assert t.denial_count("bash") == 0
