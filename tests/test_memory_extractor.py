"""Tests for :mod:`cli.memory.extractor`."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from cli.llm.provider_capabilities import ProviderCapabilities
from cli.memory.extractor import (
    DEDUP_DESCRIPTION_SIMILARITY,
    MAX_MEMORIES_PER_SESSION,
    MAX_MEMORIES_PER_TURN,
    ExtractionResult,
    _similarity,
    extract_memories,
)
from cli.memory.types import Memory, MemoryType


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeTextBlock:
    text: str


@dataclass
class _FakeResponse:
    blocks: list[Any]


def _caps(json_mode: bool = True) -> ProviderCapabilities:
    return ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=True,
        thinking=False,
        prompt_cache=True,
        vision=False,
        json_mode=json_mode,
        max_context_tokens=128_000,
        max_output_tokens=4_096,
    )


class FakeModelClient:
    """Scripted :class:`ModelClient` for tests.

    Captures every ``complete()`` kwarg into ``last_request_options`` so
    tests can assert on ``response_format`` and friends without touching
    a real provider.
    """

    def __init__(
        self,
        response_text: str,
        capabilities: ProviderCapabilities | None = None,
        *,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.capabilities = capabilities or _caps(json_mode=True)
        self.raise_on_call = raise_on_call
        self.last_request_options: dict[str, Any] = {}
        self.call_count = 0

    def complete(self, **kwargs: Any) -> _FakeResponse:
        self.call_count += 1
        self.last_request_options = dict(kwargs)
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return _FakeResponse(blocks=[_FakeTextBlock(self.response_text)])

    def stream(self, **kwargs: Any):  # pragma: no cover - not used
        raise NotImplementedError

    def cache_hint(self, blocks: list[Any]) -> None:  # pragma: no cover
        pass


def _mem_dict(
    name: str,
    *,
    type_: str = "project",
    description: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type_,
        "description": description or f"description for {name}",
        "body": body or f"body for {name}",
    }


def _mem(
    name: str,
    *,
    description: str = "",
    type_: MemoryType = MemoryType.PROJECT,
) -> Memory:
    return Memory(
        name=name,
        type=type_,
        description=description or f"description for {name}",
        body=f"body for {name}",
        created_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_extract_happy_path_json_mode_true() -> None:
    payload = json.dumps(
        {"memories": [_mem_dict("foo"), _mem_dict("bar")]}
    )
    client = FakeModelClient(payload, _caps(json_mode=True))
    result = extract_memories(
        turn_text="some turn",
        existing_memories=[],
        model_client=client,
        session_id="sess-1",
    )
    assert isinstance(result, ExtractionResult)
    assert [m.name for m in result.memories] == ["foo", "bar"]
    assert result.dropped_cap == 0
    assert result.dropped_dup == 0
    assert result.warnings == ()
    # json_mode=True → response_format kwarg forwarded.
    assert client.last_request_options.get("response_format") == {
        "type": "json_object"
    }


def test_extract_happy_path_json_mode_false_with_prose() -> None:
    payload = (
        "Sure, here's the JSON:\n"
        "```json\n"
        + json.dumps({"memories": [_mem_dict("foo")]})
        + "\n```\n"
    )
    client = FakeModelClient(payload, _caps(json_mode=False))
    result = extract_memories(
        turn_text="turn",
        existing_memories=[],
        model_client=client,
        session_id="sess-1",
    )
    assert [m.name for m in result.memories] == ["foo"]
    # json_mode=False → response_format NOT passed.
    assert "response_format" not in client.last_request_options


# --------------------------------------------------------------------------- #
# Failure modes — never raise                                                 #
# --------------------------------------------------------------------------- #


def test_empty_response_returns_empty_with_warning() -> None:
    client = FakeModelClient("", _caps(json_mode=True))
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
    )
    assert result.memories == ()
    assert any("empty model response" in w for w in result.warnings)


def test_invalid_json_returns_empty_with_warning() -> None:
    client = FakeModelClient("this is not JSON at all", _caps(json_mode=True))
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
    )
    assert result.memories == ()
    assert any("extractor schema violation" in w for w in result.warnings)


def test_model_exception_returns_empty_with_warning() -> None:
    client = FakeModelClient(
        "",
        _caps(json_mode=True),
        raise_on_call=RuntimeError("boom"),
    )
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
    )
    assert result.memories == ()
    assert any("model call failed" in w for w in result.warnings)


def test_top_level_missing_memories_key() -> None:
    client = FakeModelClient(json.dumps({"not_memories": []}), _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert result.memories == ()
    assert any("missing 'memories' key" in w for w in result.warnings)


def test_top_level_json_is_array_not_object() -> None:
    client = FakeModelClient(json.dumps([]), _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert result.memories == ()
    assert any("not an object" in w for w in result.warnings)


def test_skip_turn_no_durable_info() -> None:
    client = FakeModelClient(json.dumps({"memories": []}), _caps())
    result = extract_memories(
        turn_text="just chitchat", existing_memories=[], model_client=client
    )
    assert result.memories == ()
    # Empty list is legitimate — no warning.
    assert result.warnings == ()


# --------------------------------------------------------------------------- #
# Caps                                                                        #
# --------------------------------------------------------------------------- #


def test_per_turn_cap_drops_excess() -> None:
    payload = json.dumps(
        {"memories": [_mem_dict(f"m_{i}") for i in range(5)]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        max_per_turn=3,
        max_per_session=100,
    )
    assert [m.name for m in result.memories] == ["m_0", "m_1", "m_2"]
    assert result.dropped_cap == 2


def test_per_session_cap_drops_excess() -> None:
    payload = json.dumps(
        {"memories": [_mem_dict(f"m_{i}") for i in range(3)]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        session_extraction_count=4,
        max_per_turn=3,
        max_per_session=5,
    )
    # Only 1 slot left in the session budget.
    assert [m.name for m in result.memories] == ["m_0"]
    assert result.dropped_cap == 2


def test_per_session_cap_exactly_at_max_keeps_all() -> None:
    payload = json.dumps(
        {"memories": [_mem_dict(f"m_{i}") for i in range(2)]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        session_extraction_count=3,
        max_per_turn=3,
        max_per_session=5,
    )
    assert [m.name for m in result.memories] == ["m_0", "m_1"]
    assert result.dropped_cap == 0


def test_per_session_cap_already_exceeded_drops_all() -> None:
    payload = json.dumps({"memories": [_mem_dict("m_0")]})
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        session_extraction_count=10,
        max_per_turn=3,
        max_per_session=5,
    )
    assert result.memories == ()
    assert result.dropped_cap == 1


def test_both_caps_fire_separately() -> None:
    # Model returns 5 — per-turn cap (3) drops 2, per-session (4 left) keeps all 3.
    payload = json.dumps(
        {"memories": [_mem_dict(f"m_{i}") for i in range(5)]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        session_extraction_count=0,
        max_per_turn=3,
        max_per_session=10,
    )
    assert [m.name for m in result.memories] == ["m_0", "m_1", "m_2"]
    assert result.dropped_cap == 2


# --------------------------------------------------------------------------- #
# Dedup                                                                       #
# --------------------------------------------------------------------------- #


def test_dedup_exact_name_match() -> None:
    existing = [_mem("foo", description="very distinct wording alpha")]
    payload = json.dumps(
        {
            "memories": [
                _mem_dict(
                    "foo",
                    description="completely unrelated text about beta",
                ),
                _mem_dict("bar"),
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=existing,
        model_client=client,
    )
    assert [m.name for m in result.memories] == ["bar"]
    assert result.dropped_dup == 1


def test_dedup_description_similarity_trips_threshold() -> None:
    existing = [_mem("proj_pg", description="project uses postgres")]
    payload = json.dumps(
        {
            "memories": [
                _mem_dict(
                    "proj_postgresql",
                    description="project uses postgres",
                )
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=existing,
        model_client=client,
    )
    assert result.memories == ()
    assert result.dropped_dup == 1


def test_dedup_borderline_similarity_kept() -> None:
    # Descriptions share < DEDUP_DESCRIPTION_SIMILARITY trigrams.
    existing = [_mem("a", description="uses postgres for storage")]
    payload = json.dumps(
        {
            "memories": [
                _mem_dict(
                    "b",
                    description="uses redis for cache queues",
                )
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=existing,
        model_client=client,
    )
    assert [m.name for m in result.memories] == ["b"]
    assert result.dropped_dup == 0


# --------------------------------------------------------------------------- #
# Per-memory schema violations                                                #
# --------------------------------------------------------------------------- #


def test_schema_violation_invalid_type_drops_one_keeps_others() -> None:
    payload = json.dumps(
        {
            "memories": [
                _mem_dict("good_one", type_="project"),
                _mem_dict("bad_one", type_="invalid_type"),
                _mem_dict("another_good"),
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["good_one", "another_good"]
    assert any("type" in w.lower() for w in result.warnings)


def test_schema_violation_oversized_name_dropped() -> None:
    huge = "x" * 200
    payload = json.dumps(
        {"memories": [_mem_dict(huge), _mem_dict("ok")]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["ok"]
    assert any("name" in w.lower() for w in result.warnings)


def test_schema_violation_unsafe_slug_dropped() -> None:
    payload = json.dumps(
        {
            "memories": [
                _mem_dict("has/slash"),
                _mem_dict("Bad Caps"),
                _mem_dict("ok_name"),
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["ok_name"]
    # At least one slug warning for each violation.
    assert sum("slug-safe" in w for w in result.warnings) >= 2


def test_schema_violation_missing_field_dropped() -> None:
    payload = json.dumps(
        {
            "memories": [
                {"name": "no_type", "description": "d", "body": "b"},
                _mem_dict("good"),
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["good"]
    assert any("required" in w for w in result.warnings)


def test_schema_violation_oversized_body_dropped() -> None:
    payload = json.dumps(
        {
            "memories": [
                _mem_dict("big_body", body="x" * 2000),
                _mem_dict("ok"),
            ]
        }
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["ok"]
    assert any("body" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
# Metadata on emitted memories                                                #
# --------------------------------------------------------------------------- #


def test_source_session_id_populated() -> None:
    payload = json.dumps({"memories": [_mem_dict("foo")]})
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t",
        existing_memories=[],
        model_client=client,
        session_id="my-session-42",
    )
    assert result.memories[0].source_session_id == "my-session-42"


def test_created_at_populated_and_tz_aware() -> None:
    payload = json.dumps({"memories": [_mem_dict("foo")]})
    client = FakeModelClient(payload, _caps())
    before = datetime.now(tz=timezone.utc)
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    after = datetime.now(tz=timezone.utc)
    mem = result.memories[0]
    assert mem.created_at.tzinfo is not None
    assert before <= mem.created_at <= after


# --------------------------------------------------------------------------- #
# _similarity unit                                                            #
# --------------------------------------------------------------------------- #


def test_similarity_identical_strings() -> None:
    assert _similarity("hello world", "hello world") == 1.0


def test_similarity_disjoint_strings() -> None:
    # No shared trigrams.
    assert _similarity("abcdef", "xyzuvw") == 0.0


def test_similarity_partial_overlap_is_in_range() -> None:
    # "the project uses postgres" vs "the project uses postgresql"
    # share many trigrams — expect > 0.9 (why we set the dedup threshold).
    score = _similarity(
        "the project uses postgres",
        "the project uses postgresql",
    )
    assert score > DEDUP_DESCRIPTION_SIMILARITY
    assert score < 1.0


def test_similarity_both_empty_returns_one() -> None:
    assert _similarity("", "") == 1.0


def test_similarity_one_empty_returns_zero() -> None:
    assert _similarity("", "anything") == 0.0


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #


def test_default_caps_match_module_constants() -> None:
    assert MAX_MEMORIES_PER_TURN == 3
    assert MAX_MEMORIES_PER_SESSION == 5
    assert 0.0 < DEDUP_DESCRIPTION_SIMILARITY <= 1.0


# --------------------------------------------------------------------------- #
# In-batch dedup                                                              #
# --------------------------------------------------------------------------- #


def test_in_batch_duplicate_names_deduped() -> None:
    payload = json.dumps(
        {"memories": [_mem_dict("foo"), _mem_dict("foo")]}
    )
    client = FakeModelClient(payload, _caps())
    result = extract_memories(
        turn_text="t", existing_memories=[], model_client=client
    )
    assert [m.name for m in result.memories] == ["foo"]
    assert result.dropped_dup == 1
