"""Tests for Ctrl-T transcript view toggling (S3)."""

from __future__ import annotations

from cli.workbench_app.output_collapse import (
    TranscriptView,
    TranscriptViewState,
    toggle_transcript_view,
)
from cli.workbench_app.pt_prompt import WorkbenchPromptState


def test_default_view_is_collapsed() -> None:
    state = TranscriptViewState()
    assert state.view is TranscriptView.COLLAPSED
    assert state.is_raw is False
    assert state.label == "collapsed"


def test_toggle_flips_back_and_forth() -> None:
    state = TranscriptViewState()
    assert state.toggle() is TranscriptView.RAW
    assert state.is_raw is True
    assert state.label == "raw events"
    assert state.toggle() is TranscriptView.COLLAPSED
    assert state.is_raw is False


def test_toggle_transcript_view_helper_matches_method() -> None:
    state = TranscriptViewState()
    assert toggle_transcript_view(state) is TranscriptView.RAW
    assert toggle_transcript_view(state) is TranscriptView.COLLAPSED


def test_workbench_prompt_state_owns_transcript_view() -> None:
    state = WorkbenchPromptState()
    assert isinstance(state.transcript_view, TranscriptViewState)
    assert state.transcript_view_cycles == 0
    new_view = state.transcript_view.toggle()
    state.transcript_view_cycles += 1
    assert new_view is TranscriptView.RAW
    assert state.transcript_view_cycles == 1
