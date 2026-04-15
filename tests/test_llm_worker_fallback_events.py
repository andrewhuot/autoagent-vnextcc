"""Fallback & retry event surfacing for :class:`LLMWorkerAdapter`.

These tests lock in the Chunk-1 contract from
``/Users/andrew/.claude/plans/declarative-stargazing-rocket.md``:

1. Parse / provider failures must emit a first-class ``LLM_FALLBACK`` event
   through the builder event broker *and* through the stream-json sink so the
   `/build` REPL handler can render a banner instead of a cryptic log line.
2. A JSON-parse failure must emit ``LLM_RETRY`` before the stricter retry,
   then ``LLM_FALLBACK`` if the retry also fails.
3. Artifacts returned by the deterministic fallback must be stamped with
   ``source="deterministic-fallback"`` plus a ``fallback_reason`` crumb so
   downstream renderers can badge them as placeholders.
"""

from __future__ import annotations

import json
from typing import Any

from builder.events import BuilderEventType, EventBroker
from builder.llm_worker import LLMWorkerAdapter
from builder.types import SpecialistRole, WorkerExecutionResult
from optimizer.providers import LLMRequest, LLMResponse

# Reuse the adapter-context builder from the existing suite to keep fixtures
# in one place. Import lazily so test collection doesn't explode if that file
# moves.
from tests.test_llm_worker_adapter import _make_adapter_context


class _RouterFromResponses:
    """Yield a pre-baked sequence of responses and remember every request."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        text = self._responses.pop(0) if self._responses else ""
        return LLMResponse(
            provider="fake",
            model="fake-model",
            text=text,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
        )


class _ExplodingRouter:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        raise self._exc


def _collect_sink() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    sink_events: list[tuple[str, dict[str, Any]]] = []

    def _sink(event_name: str, payload: dict[str, Any]) -> None:
        sink_events.append((event_name, payload))

    return sink_events, _sink


def test_provider_error_emits_fallback_event_without_retry() -> None:
    """A provider exception should emit a single fallback event (no retry)."""
    sink_events, sink = _collect_sink()
    adapter = LLMWorkerAdapter(
        router=_ExplodingRouter(RuntimeError("quota exceeded")),  # type: ignore[arg-type]
        event_sink=sink,
    )
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    assert isinstance(result, WorkerExecutionResult)
    # One fallback event, no retry event — provider never spoke.
    assert [name for name, _ in sink_events] == [
        BuilderEventType.LLM_FALLBACK.value,
    ]
    _, payload = sink_events[0]
    assert payload["reason"] == "provider_error"
    assert payload["attempts"] == 1
    assert payload["worker_role"] == SpecialistRole.BUILD_ENGINEER.value

    # Broker also received the same event type — verifies the dual publish.
    broker_events = [
        ev
        for ev in context.events.list_events(
            session_id=context.run.session_id, limit=10
        )
        if ev.event_type == BuilderEventType.LLM_FALLBACK
    ]
    assert len(broker_events) == 1
    assert broker_events[0].payload["reason"] == "provider_error"

    # Fallback-labeled artifact payloads so the UI can badge them as stubs.
    assert result.output_payload["adapter"] == "deterministic_worker_adapter"
    assert result.output_payload["source"] == "deterministic-fallback"
    assert result.output_payload["fallback_reason"] == "provider_error"
    for artifact in result.artifacts.values():
        assert artifact["source"] == "deterministic-fallback"
        assert artifact["fallback_reason"] == "provider_error"


def test_non_json_response_emits_retry_then_fallback() -> None:
    """Parse failure must retry once; a second failure triggers fallback."""
    sink_events, sink = _collect_sink()
    router = _RouterFromResponses(
        [
            "definitely not json",
            "still not json after the strict retry",
        ]
    )
    adapter = LLMWorkerAdapter(router=router, event_sink=sink)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    # Order matters: retry precedes the fallback banner so the user sees
    # "we tried again, then gave up".
    emitted = [name for name, _ in sink_events]
    assert emitted == [
        BuilderEventType.LLM_RETRY.value,
        BuilderEventType.LLM_FALLBACK.value,
    ]
    # Two provider calls proves the retry actually happened.
    assert len(router.calls) == 2

    _, fallback_payload = sink_events[1]
    assert fallback_payload["attempts"] == 2
    assert fallback_payload["reason"] in {
        "no_json_object",
        "json_decode_error",
        "not_mapping",
        "missing_required_keys",
    }
    assert result.output_payload["source"] == "deterministic-fallback"


def test_successful_first_call_emits_no_fallback_events() -> None:
    """Happy path must not leak fallback/retry noise to the transcript."""
    sink_events, sink = _collect_sink()
    router = _RouterFromResponses(
        [
            json.dumps(
                {
                    "summary": "ok",
                    "artifacts": {"agent_config_candidate": {"stub": True}},
                    "output_payload": {},
                }
            )
        ]
    )
    adapter = LLMWorkerAdapter(router=router, event_sink=sink)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    fallback_names = {
        BuilderEventType.LLM_FALLBACK.value,
        BuilderEventType.LLM_RETRY.value,
    }
    assert not any(name in fallback_names for name, _ in sink_events)
    assert result.output_payload["source"] == "llm"
    assert result.output_payload["adapter"] == LLMWorkerAdapter.name


def test_missing_expected_artifacts_emits_fallback_with_detail() -> None:
    """The envelope parsed fine but lacked the required artifact key."""
    sink_events, sink = _collect_sink()
    router = _RouterFromResponses(
        [
            json.dumps(
                {
                    "summary": "missing",
                    "artifacts": {"something_unrelated": {}},
                    "output_payload": {},
                }
            )
        ]
    )
    adapter = LLMWorkerAdapter(router=router, event_sink=sink)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    emitted = [(name, payload) for name, payload in sink_events]
    fallback_matches = [p for n, p in emitted if n == BuilderEventType.LLM_FALLBACK.value]
    assert len(fallback_matches) == 1
    payload = fallback_matches[0]
    assert payload["reason"] == "missing_expected_artifacts"
    assert payload["detail"]["expected"] == ["agent_config_candidate"]
    assert result.output_payload["source"] == "deterministic-fallback"
    assert result.output_payload["fallback_reason"] == "missing_expected_artifacts"


def test_default_sink_is_gated_on_stream_json_env(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Outside a stream-json window the default sink must stay silent."""
    monkeypatch.delenv("AGENTLAB_WORKBENCH_STREAM_JSON", raising=False)
    adapter = LLMWorkerAdapter(router=_ExplodingRouter(RuntimeError("x")))  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    adapter.execute(context)

    captured = capsys.readouterr()
    # No stray JSON lines on stdout — they would corrupt normal CLI output.
    assert "llm.fallback" not in captured.out
    assert captured.out == ""


def test_default_sink_emits_json_when_stream_json_flag_set(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """With the env flag set, the sink must emit one JSON line per event."""
    monkeypatch.setenv("AGENTLAB_WORKBENCH_STREAM_JSON", "1")
    adapter = LLMWorkerAdapter(router=_ExplodingRouter(RuntimeError("nope")))  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    adapter.execute(context)

    out = capsys.readouterr().out.strip().splitlines()
    assert any('"event": "llm.fallback"' in line for line in out)
    # Confirm the JSON is well-formed and carries the structured payload.
    payloads = [json.loads(line) for line in out]
    fallback = next(p for p in payloads if p["event"] == "llm.fallback")
    assert fallback["data"]["reason"] == "provider_error"
