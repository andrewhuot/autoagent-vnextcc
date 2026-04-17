"""Chunk 6 integration tests — live markdown streaming through the orchestrator.

These tests pin the contract that :class:`LLMOrchestrator` feeds every
``TextDelta`` it receives into :class:`StreamingMarkdownRenderer` as the
chunks arrive — rather than buffering the whole assistant turn and echoing
it after ``end_turn``. The user-facing win is visible "token-by-token"
output: the REPL starts printing the reply before the model finishes
thinking, and fenced code blocks keep their language-aware styling even
when a fence marker straddles chunk boundaries.

The test double is a scripted streaming model that yields ``TextDelta``
events one at a time; the orchestrator calls ``echo`` for each complete
line, and we assert the echo sink sees lines in the order/number we expect.

Companion coverage:

* :mod:`tests.test_phase_a_model_adapters` — exercises the streaming
  primitives (``collect_stream``, ``events_from_model_response``) in
  isolation.
* :mod:`tests.test_markdown_stream` — unit-tests the renderer state machine.
  This file's role is the *integration* glue — that the two halves meet in
  the orchestrator without a buffering regression.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.streaming import MessageStop, TextDelta, ThinkingDelta
from cli.llm.types import TurnMessage
from cli.permissions import PermissionManager
from cli.tools.registry import ToolRegistry
from cli.workbench_app.markdown_stream import BlockMode


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _ScriptedStreamingModel:
    """Streaming stub that yields scripted events one at a time.

    Each call to :meth:`stream` consumes one scripted turn. The generator
    yields events lazily so the test harness can observe the orchestrator's
    intermediate state between deltas — specifically, it can assert that
    the renderer emitted a line *before* the next delta arrives, which is
    how we prove streaming (vs. buffering) at the integration level.
    """

    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = list(turns)
        self.call_count = 0

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        del system_prompt, messages, tools  # unused in these tests
        self.call_count += 1
        events = self._turns.pop(0) if self._turns else [MessageStop(stop_reason="end_turn")]
        for event in events:
            yield event


def _build_orchestrator(
    tmp_path: Path,
    model: _ScriptedStreamingModel,
    *,
    echo_sink: list[str],
    styler: Any | None = None,
) -> LLMOrchestrator:
    (tmp_path / ".agentlab").mkdir(exist_ok=True)
    return LLMOrchestrator(
        model=model,
        tool_registry=ToolRegistry(),
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        echo=echo_sink.append,
        styler=styler,
    )


def _mode_tagger():
    """Styler that prefixes each line with its mode — lets tests assert
    transitions between prose / code / diff without parsing ANSI escapes."""

    def _style(line: str, mode: BlockMode, fence_language: str) -> str:
        tag = mode.value
        if fence_language and mode is not BlockMode.PROSE:
            tag = f"{tag}:{fence_language}"
        return f"[{tag}] {line}"

    return _style


# ---------------------------------------------------------------------------
# TextDelta chunks land in the renderer incrementally
# ---------------------------------------------------------------------------


def test_text_deltas_emit_one_line_per_newline(tmp_path: Path) -> None:
    """A multi-line reply split across chunks should produce one echo per
    complete line — proving the renderer consumed deltas as they arrived
    rather than concatenating them and emitting on ``finalize``."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text="First line.\n"),
                TextDelta(text="Second "),
                TextDelta(text="line.\n"),
                TextDelta(text="Third line."),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo)
    result = orch.run_turn("hi")

    assert echo == ["First line.", "Second line.", "Third line."]
    assert result.assistant_text == "First line.\nSecond line.\nThird line.\n"


def test_text_delta_partial_line_waits_for_newline(tmp_path: Path) -> None:
    """Partial lines must not flush until a newline (or stream end) arrives.
    Otherwise word-fragment echos would repeatedly rewrite the same line."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text="partial "),
                TextDelta(text="still-partial "),
                TextDelta(text="complete.\n"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo)
    orch.run_turn("hi")

    # Exactly one echo — the renderer held partials together until ``\n``.
    assert echo == ["partial still-partial complete."]


def test_fenced_code_block_styling_survives_chunk_splits(tmp_path: Path) -> None:
    """A fence that arrives across two chunks must still switch the renderer
    into ``CODE`` mode for the payload lines. This is the "streaming preserves
    fence styling" promise that Chunk 6 is meant to guarantee."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text="Intro prose.\n```"),  # fence opens across split
                TextDelta(text="python\n"),
                TextDelta(text="print('hi')\n"),
                TextDelta(text="```\n"),  # closing fence
                TextDelta(text="Outro prose.\n"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo, styler=_mode_tagger())
    orch.run_turn("hi")

    assert echo == [
        "[prose] Intro prose.",
        "[prose] ```python",
        "[code:python] print('hi')",
        "[prose] ```",
        "[prose] Outro prose.",
    ]


def test_diff_fence_styles_plus_minus_lines_through_streaming(tmp_path: Path) -> None:
    """``+``/``-`` lines inside a ``diff`` fence should render in DIFF mode even
    when each line lands as its own ``TextDelta``."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text="```diff\n"),
                TextDelta(text="+ added\n"),
                TextDelta(text="- removed\n"),
                TextDelta(text="  context\n"),
                TextDelta(text="```\n"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo, styler=_mode_tagger())
    orch.run_turn("hi")

    assert echo == [
        "[prose] ```diff",
        "[diff:diff] + added",
        "[diff:diff] - removed",
        "[diff:diff]   context",
        "[prose] ```",
    ]


def test_trailing_partial_line_flushes_at_end_of_turn(tmp_path: Path) -> None:
    """The model can close the stream on a trailing partial line (no final
    newline). The orchestrator appends a newline before calling
    ``finalize`` so the last line still echoes exactly once."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text="No trailing newline"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo)
    orch.run_turn("hi")

    assert echo == ["No trailing newline"]


def test_output_style_directive_renders_json_without_echoing_raw_tag(tmp_path: Path) -> None:
    """A style directive at byte 0 should be stripped from the live transcript,
    and JSON output should render only after the full payload is available."""
    model = _ScriptedStreamingModel(
        [
            [
                TextDelta(text='<agentlab output-style="jso'),
                TextDelta(text='n">{"ok": true}'),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo, styler=_mode_tagger())
    result = orch.run_turn("hi")

    assert echo == [
        "[prose] ```json",
        '[code:json] {"ok": true}',
        "[prose] ```",
    ]
    assert result.assistant_text == '<agentlab output-style="json">{"ok": true}\n'


# ---------------------------------------------------------------------------
# ThinkingDelta is intentionally NOT routed into the main renderer
# ---------------------------------------------------------------------------


def test_thinking_delta_does_not_leak_into_main_transcript(tmp_path: Path) -> None:
    """Chain-of-thought surfaces on a dedicated indicator (outside this
    test's scope) — the main assistant stream must stay focused on
    user-visible prose, so ``ThinkingDelta`` events must *not* reach the
    markdown echo sink."""
    model = _ScriptedStreamingModel(
        [
            [
                ThinkingDelta(text="the model mulls it over"),
                TextDelta(text="Here is the answer.\n"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo)
    result = orch.run_turn("hi")

    assert echo == ["Here is the answer."]
    assert "mulls" not in result.assistant_text


# ---------------------------------------------------------------------------
# Streaming is observable *during* the turn, not only after finalize
# ---------------------------------------------------------------------------


def test_echo_fires_before_stream_completion(tmp_path: Path) -> None:
    """Drive the orchestrator against a model that records the echo sink
    length at each delta — proves the first line is echoed before the
    second delta is pulled, i.e. streaming, not batching."""

    observations: list[int] = []

    class _ObservingModel:
        def stream(
            self,
            *,
            system_prompt: str,
            messages: list[TurnMessage],
            tools: list[dict[str, Any]],
        ) -> Iterator[Any]:
            del system_prompt, messages, tools
            yield TextDelta(text="line one.\n")
            # Record echo sink *before* yielding the next delta. If the
            # orchestrator were buffering, this would still be 0.
            observations.append(len(echo))
            yield TextDelta(text="line two.\n")
            observations.append(len(echo))
            yield MessageStop(stop_reason="end_turn")

    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, _ObservingModel(), echo_sink=echo)
    orch.run_turn("hi")

    # First observation is after "line one." — sink length should be 1.
    # Second is after "line two." — sink length should be 2.
    assert observations == [1, 2]
    assert echo == ["line one.", "line two."]


# ---------------------------------------------------------------------------
# Assistant text returned by run_turn stays byte-identical to concatenated deltas
# ---------------------------------------------------------------------------


def test_assistant_text_matches_concatenated_deltas(tmp_path: Path) -> None:
    """The renderer is a passthrough — nothing it does to style the live
    output should corrupt the canonical ``OrchestratorResult.assistant_text``
    that callers persist into session history."""
    chunks = [
        "Here's a plan:\n",
        "1. Read the file.\n",
        "2. Edit it.\n",
        "```py\n",
        "print('ok')\n",
        "```\n",
        "All done.",
    ]
    model = _ScriptedStreamingModel(
        [[TextDelta(text=c) for c in chunks] + [MessageStop(stop_reason="end_turn")]]
    )
    echo: list[str] = []
    orch = _build_orchestrator(tmp_path, model, echo_sink=echo)
    result = orch.run_turn("hi")

    # The orchestrator's ``_run_model_turn`` appends a synthetic ``\n`` when
    # the final chunk doesn't end on a newline, so the collected text has
    # one extra trailing ``\n`` beyond the raw chunks.
    assert result.assistant_text == "".join(chunks) + "\n"
