"""Tests for ``cli/llm/digests.py`` — tool-phase digest generator.

Pure-module tests: no SDK imports, no live models, no I/O. Fake model
clients are built with ``SimpleNamespace`` inline — we keep them local
to this file rather than shared-fixtures so each test reads top-to-
bottom without cross-file navigation.
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from cli.llm.digests import (
    BIG_BLOB_BYTES,
    ToolUseSummaryMessage,
    choose_strategy,
    digest_tool_phase,
    group_tool_phase,
)
from cli.llm.types import TurnMessage


# ---------------------------------------------------------------------------
# Helpers — local fakes for messages, tool blocks, and model clients.
# ---------------------------------------------------------------------------


def _tool_use_block(name: str, id_: str = "toolu_1") -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": {}}


def _tool_result_block(content: str, *, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": content,
        "is_error": is_error,
    }


def _assistant_tool_turn(*blocks: dict) -> TurnMessage:
    return TurnMessage(role="assistant", content=list(blocks))


def _user_tool_result_turn(*blocks: dict) -> TurnMessage:
    return TurnMessage(role="user", content=list(blocks))


def _text_turn(text: str, role: str = "assistant") -> TurnMessage:
    return TurnMessage(role=role, content=text)


def _fake_response(text: str) -> SimpleNamespace:
    """Duck-typed :class:`ModelResponse` with a ``text_blocks()`` method."""
    block = SimpleNamespace(text=text)
    return SimpleNamespace(text_blocks=lambda: [block], text=text)


def _fake_client_returning(text: str) -> SimpleNamespace:
    return SimpleNamespace(complete=lambda **_kw: _fake_response(text))


def _fake_client_raising(exc: Exception) -> SimpleNamespace:
    def _boom(**_kw):
        raise exc

    return SimpleNamespace(complete=_boom)


# ---------------------------------------------------------------------------
# group_tool_phase
# ---------------------------------------------------------------------------


def test_group_tool_phase_empty_range_returns_empty():
    transcript: list[TurnMessage] = []
    assert group_tool_phase(transcript, 0, 0) == []


def test_group_tool_phase_single_tool_turn_is_one_range():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
    ]
    assert group_tool_phase(transcript, 0, 1) == [(0, 1)]


def test_group_tool_phase_tool_text_tool_splits_into_three_ranges():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _text_turn("thinking out loud"),
        _assistant_tool_turn(_tool_use_block("file_read")),
    ]
    assert group_tool_phase(transcript, 0, 3) == [(0, 1), (1, 2), (2, 3)]


def test_group_tool_phase_consecutive_tool_calls_merge():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("match 1")),
        _assistant_tool_turn(_tool_use_block("file_read")),
        _user_tool_result_turn(_tool_result_block("contents")),
    ]
    assert group_tool_phase(transcript, 0, 4) == [(0, 4)]


# ---------------------------------------------------------------------------
# choose_strategy
# ---------------------------------------------------------------------------


def test_choose_strategy_all_small_results_is_abstractive():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("small output")),
    ]
    assert choose_strategy(transcript) == "abstractive"


def test_choose_strategy_one_big_blob_flips_to_extractive():
    big = "x" * (BIG_BLOB_BYTES + 500)
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block(big)),
    ]
    assert choose_strategy(transcript) == "extractive"


def test_choose_strategy_exactly_at_threshold_stays_abstractive():
    # Strict `>` — equal-to-threshold does NOT flip.
    body = "x" * BIG_BLOB_BYTES
    transcript = [_user_tool_result_turn(_tool_result_block(body))]
    assert choose_strategy(transcript) == "abstractive"


def test_choose_strategy_just_over_threshold_is_extractive():
    body = "x" * (BIG_BLOB_BYTES + 1)
    transcript = [_user_tool_result_turn(_tool_result_block(body))]
    assert choose_strategy(transcript) == "extractive"


# ---------------------------------------------------------------------------
# digest_tool_phase — extractive branch
# ---------------------------------------------------------------------------


def test_digest_no_model_factory_falls_back_with_warning(caplog):
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("tiny")),
    ]
    with caplog.at_level(logging.WARNING, logger="cli.llm.digests"):
        digest = digest_tool_phase(transcript, 0, 2, model_factory=None)
    assert digest.strategy == "extractive"
    assert any("model_factory is None" in rec.message for rec in caplog.records)


def test_extractive_100_line_result_uses_head_tail_and_omission_marker():
    body = "\n".join(f"line-{i}" for i in range(100))
    transcript = [
        _assistant_tool_turn(_tool_use_block("file_read")),
        _user_tool_result_turn(_tool_result_block(body)),
    ]
    digest = digest_tool_phase(transcript, 0, 2, model_factory=None)
    assert digest.strategy == "extractive"
    assert "line-0" in digest.summary
    assert "line-99" in digest.summary
    # 100 - 20 - 20 = 60 lines omitted
    assert "60 lines omitted" in digest.summary
    # The middle lines should NOT be present.
    assert "line-50" not in digest.summary


def test_extractive_30_line_result_is_preserved_intact():
    body = "\n".join(f"line-{i}" for i in range(30))
    transcript = [
        _assistant_tool_turn(_tool_use_block("file_read")),
        _user_tool_result_turn(_tool_result_block(body)),
    ]
    digest = digest_tool_phase(transcript, 0, 2, model_factory=None)
    assert digest.strategy == "extractive"
    for i in range(30):
        assert f"line-{i}" in digest.summary
    assert "omitted" not in digest.summary


def test_extractive_preserves_tool_names_in_order():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep", id_="t1")),
        _user_tool_result_turn(_tool_result_block("g")),
        _assistant_tool_turn(_tool_use_block("file_read", id_="t2")),
        _user_tool_result_turn(_tool_result_block("r")),
        _assistant_tool_turn(_tool_use_block("grep", id_="t3")),
        _user_tool_result_turn(_tool_result_block("g2")),
    ]
    digest = digest_tool_phase(transcript, 0, 6, model_factory=None)
    assert digest.tool_names == ("grep", "file_read", "grep")


def test_extractive_byte_accounting_is_correct():
    body = "hello world"
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block(body)),
    ]
    digest = digest_tool_phase(transcript, 0, 2, model_factory=None)
    # total_bytes_in covers every message's stringified content; summary's
    # utf-8 byte length is the out side.
    assert digest.total_bytes_in > 0
    assert digest.total_bytes_out == len(digest.summary.encode("utf-8"))


# ---------------------------------------------------------------------------
# digest_tool_phase — abstractive branch
# ---------------------------------------------------------------------------


def test_abstractive_uses_fake_client_completion_text():
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("one match in foo.py")),
    ]
    client = _fake_client_returning("grep found one match in foo.py")
    digest = digest_tool_phase(
        transcript, 0, 2, model_factory=lambda: client
    )
    assert digest.strategy == "abstractive"
    assert digest.summary == "grep found one match in foo.py"
    assert digest.original_turn_count == 2


def test_abstractive_factory_raising_falls_back_to_extractive(caplog):
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("small")),
    ]

    def _bad_factory():
        raise RuntimeError("no credentials")

    with caplog.at_level(logging.ERROR, logger="cli.llm.digests"):
        digest = digest_tool_phase(
            transcript, 0, 2, model_factory=_bad_factory
        )
    assert digest.strategy == "extractive"
    assert any("model_factory" in rec.message for rec in caplog.records)


def test_abstractive_client_complete_raising_falls_back(caplog):
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("small")),
    ]
    client = _fake_client_raising(RuntimeError("provider 500"))
    with caplog.at_level(logging.ERROR, logger="cli.llm.digests"):
        digest = digest_tool_phase(
            transcript, 0, 2, model_factory=lambda: client
        )
    assert digest.strategy == "extractive"
    assert any("complete()" in rec.message for rec in caplog.records)


def test_abstractive_empty_completion_falls_back(caplog):
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep")),
        _user_tool_result_turn(_tool_result_block("small")),
    ]
    client = _fake_client_returning("   ")  # whitespace-only → empty
    with caplog.at_level(logging.WARNING, logger="cli.llm.digests"):
        digest = digest_tool_phase(
            transcript, 0, 2, model_factory=lambda: client
        )
    assert digest.strategy == "extractive"
    assert any("empty completion" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# ToolUseSummaryMessage frozen-ness
# ---------------------------------------------------------------------------


def test_tool_use_summary_message_is_frozen():
    msg = ToolUseSummaryMessage(
        tool_names=("grep",),
        strategy="extractive",
        summary="x",
        original_turn_count=1,
        total_bytes_in=10,
        total_bytes_out=1,
    )
    with pytest.raises(FrozenInstanceError):
        msg.summary = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Snapshot — deterministic canned transcript
# ---------------------------------------------------------------------------


def test_snapshot_extractive_output_is_deterministic():
    """A fixed 5-turn transcript with one oversized result produces a
    byte-stable extractive digest. If this test drifts, the extractive
    renderer changed and every dependent snapshot should be rechecked."""
    big_body = "\n".join(f"row-{i}" for i in range(200))
    transcript = [
        _assistant_tool_turn(_tool_use_block("grep", id_="a")),
        _user_tool_result_turn(_tool_result_block("two hits")),
        _assistant_tool_turn(_tool_use_block("file_read", id_="b")),
        _user_tool_result_turn(_tool_result_block(big_body)),
        _assistant_tool_turn(_tool_use_block("grep", id_="c")),
    ]
    digest = digest_tool_phase(transcript, 0, 5, model_factory=None)
    assert digest.strategy == "extractive"
    assert digest.tool_names == ("grep", "file_read", "grep")
    assert digest.original_turn_count == 5
    # Head, tail, omission marker all present.
    assert "row-0" in digest.summary
    assert "row-199" in digest.summary
    assert "160 lines omitted" in digest.summary
    # Small result passes through intact.
    assert "two hits" in digest.summary
    # Deterministic prefix.
    assert digest.summary.startswith("Tool phase summary (extractive):")


# ---------------------------------------------------------------------------
# Robustness — malformed shapes never crash.
# ---------------------------------------------------------------------------


def test_digest_does_not_crash_on_malformed_shapes():
    # A message whose content is neither str nor list, plus a block with
    # no recognisable type — the digester must stringify rather than
    # raise.
    weird = TurnMessage(role="assistant", content=12345)
    odd_block = {"something": "else"}  # no `type` field
    opaque = TurnMessage(role="assistant", content=[odd_block])
    transcript = [weird, opaque]
    # Should not raise.
    digest = digest_tool_phase(transcript, 0, 2, model_factory=None)
    assert isinstance(digest, ToolUseSummaryMessage)
    assert digest.strategy == "extractive"
    assert digest.original_turn_count == 2
