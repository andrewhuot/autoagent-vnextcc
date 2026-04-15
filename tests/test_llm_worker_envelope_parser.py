"""Tests for the robust envelope parser + provider JSON-mode hooks.

Covers the bug surfaced in the Apr 2026 debug session: Gemini wraps
envelope JSON in prose (``"Sure! Here is the envelope:\n\n{...}\n\n
Let me know if you'd like to iterate."``) and the strict parser
rejected anything outside bare-JSON / fenced shapes — so every worker
in a ``/build`` turn fell through to the deterministic stub.

The fix has three layers; this module exercises all three:

1. :mod:`builder.llm_worker._parse_envelope` now returns a structured
   ``(envelope, failure_kind)`` tuple and extracts the first balanced
   JSON object from arbitrary surrounding prose.
2. :mod:`optimizer.providers` providers honour
   :attr:`LLMRequest.response_format` by setting provider-native JSON
   mode flags (Gemini ``response_mime_type``, OpenAI ``response_format``,
   Anthropic strict-directive system suffix).
3. :class:`LLMWorkerAdapter.execute` does a single retry with a stricter
   system suffix before falling back to the deterministic adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from builder.llm_worker import (
    PARSE_FAILURE_DECODE_ERROR,
    PARSE_FAILURE_MISSING_KEYS,
    PARSE_FAILURE_NOT_MAPPING,
    PARSE_FAILURE_NO_JSON_OBJECT,
    LLMWorkerAdapter,
    _parse_envelope,
    _strip_trailing_commas,
    _with_strict_suffix,
)
from optimizer.providers import (
    AnthropicProvider,
    GoogleProvider,
    LLMRequest,
    LLMResponse,
    ModelConfig,
    OpenAIProvider,
)


# ---------------------------------------------------------------------------
# Parser — happy paths
# ---------------------------------------------------------------------------


def test_parse_envelope_bare_json() -> None:
    envelope, failure = _parse_envelope(
        '{"summary": "ok", "artifacts": {"x": {"value": 1}}}'
    )
    assert failure is None
    assert envelope is not None
    assert envelope["summary"] == "ok"
    assert envelope["artifacts"]["x"] == {"value": 1}


def test_parse_envelope_fenced_with_language_tag() -> None:
    text = "```json\n" + json.dumps({"summary": "y", "artifacts": {}}) + "\n```"
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None


def test_parse_envelope_fenced_without_language_tag() -> None:
    text = "```\n" + json.dumps({"summary": "z", "artifacts": {}}) + "\n```"
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None


# ---------------------------------------------------------------------------
# Parser — the Gemini case that triggered the bug
# ---------------------------------------------------------------------------


def test_parse_envelope_tolerates_prose_preamble() -> None:
    """The exact shape Gemini emits without ``response_mime_type``."""
    text = (
        "Sure! Here is the envelope you asked for:\n\n"
        '{"summary": "built", "artifacts": {"config": {"model": "x"}}}'
    )
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None
    assert envelope["summary"] == "built"


def test_parse_envelope_tolerates_trailing_commentary() -> None:
    text = (
        '{"summary": "ok", "artifacts": {}}\n\n'
        "Let me know if you'd like me to iterate on this."
    )
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None


def test_parse_envelope_tolerates_prose_on_both_sides() -> None:
    text = (
        "Certainly — here is the envelope you requested:\n\n"
        '{"summary": "done", "artifacts": {"a": {}}}\n\n'
        "Please review and let me know."
    )
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None


def test_parse_envelope_tolerates_trailing_commas() -> None:
    # Strict JSON rejects trailing commas but Gemini emits them enough that
    # the parser offers one relaxing retry.
    text = '{"summary": "ok", "artifacts": {"a": 1,},}'
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None
    assert envelope["artifacts"] == {"a": 1}


def test_strip_trailing_commas_is_minimal() -> None:
    # Only removes commas immediately before ``}`` / ``]`` — does not
    # broadly relax JSON. A genuinely malformed payload still fails.
    assert _strip_trailing_commas('{"a": 1,}') == '{"a": 1}'
    assert _strip_trailing_commas('[1, 2,]') == "[1, 2]"
    assert _strip_trailing_commas('{"a": 1, "b": 2}') == '{"a": 1, "b": 2}'


def test_parse_envelope_nested_objects_with_braces_in_strings() -> None:
    # Ensures the balanced-brace scan respects string boundaries — a
    # literal ``{`` inside a string value must not bump the depth counter.
    text = (
        "Here goes:\n\n"
        '{"summary": "pattern uses {key}", "artifacts": {"hint": "{nested}"}}'
    )
    envelope, failure = _parse_envelope(text)
    assert failure is None
    assert envelope is not None
    assert envelope["summary"] == "pattern uses {key}"


# ---------------------------------------------------------------------------
# Parser — failure kinds
# ---------------------------------------------------------------------------


def test_parse_envelope_no_json_at_all() -> None:
    envelope, failure = _parse_envelope("No JSON here at all.")
    assert envelope is None
    assert failure == PARSE_FAILURE_NO_JSON_OBJECT


def test_parse_envelope_empty_text() -> None:
    envelope, failure = _parse_envelope("")
    assert envelope is None
    assert failure == PARSE_FAILURE_NO_JSON_OBJECT


def test_parse_envelope_truncated_json() -> None:
    # Model hit max_tokens mid-object. Balanced-brace scan never closes so
    # the extractor returns nothing — surfaces as NO_JSON_OBJECT, which is
    # the closest structured match for "brace never balanced".
    envelope, failure = _parse_envelope('{"summary": "truncated', )
    assert envelope is None
    assert failure == PARSE_FAILURE_NO_JSON_OBJECT


def test_parse_envelope_rejects_non_object_top_level() -> None:
    envelope, failure = _parse_envelope('["summary", "artifacts"]')
    assert envelope is None
    # Array has no ``{`` so the scanner skips it.
    assert failure == PARSE_FAILURE_NO_JSON_OBJECT


def test_parse_envelope_rejects_missing_required_keys() -> None:
    envelope, failure = _parse_envelope('{"summary": "no artifacts"}')
    assert envelope is None
    assert failure == PARSE_FAILURE_MISSING_KEYS


def test_parse_envelope_rejects_json_with_broken_syntax() -> None:
    # Unrecoverable JSON — not a trailing-comma issue. We want a
    # specific "the JSON you emitted is broken" failure kind.
    envelope, failure = _parse_envelope('{"summary": "a", "artifacts": [not valid}]')
    assert envelope is None
    assert failure == PARSE_FAILURE_DECODE_ERROR


# ---------------------------------------------------------------------------
# Strict-retry helper
# ---------------------------------------------------------------------------


def test_with_strict_suffix_appends_to_existing_system() -> None:
    request = LLMRequest(prompt="p", system="You are a helper.")
    retry = _with_strict_suffix(request, PARSE_FAILURE_DECODE_ERROR)
    assert retry.system is not None
    assert retry.system.startswith("You are a helper.")
    assert "single raw JSON object" in retry.system
    assert retry.metadata["retry_reason"] == PARSE_FAILURE_DECODE_ERROR


def test_with_strict_suffix_handles_missing_system() -> None:
    request = LLMRequest(prompt="p", system=None)
    retry = _with_strict_suffix(request, PARSE_FAILURE_NO_JSON_OBJECT)
    assert retry.system is not None
    assert "single raw JSON object" in retry.system


def test_with_strict_suffix_preserves_response_format() -> None:
    request = LLMRequest(prompt="p", response_format="json")
    retry = _with_strict_suffix(request, PARSE_FAILURE_DECODE_ERROR)
    assert retry.response_format == "json"


# ---------------------------------------------------------------------------
# Provider JSON-mode integration — monkeypatched HTTP so no network fires
# ---------------------------------------------------------------------------


def _model_config(provider: str, model: str = "test-model") -> ModelConfig:
    return ModelConfig(provider=provider, model=model, api_key_env="TEST_API_KEY")


def test_google_provider_sets_response_mime_type_when_json_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "candidates": [
                {"content": {"parts": [{"text": "{\"summary\":\"ok\",\"artifacts\":{}}"}]}}
            ],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }

    monkeypatch.setattr(GoogleProvider, "_http_post", fake_post)
    provider = GoogleProvider(_model_config("google", "gemini-2.5-pro"))
    provider._send_request(LLMRequest(prompt="p", response_format="json"))
    assert captured["payload"]["generationConfig"]["response_mime_type"] == "application/json"


def test_google_provider_omits_mime_type_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "candidates": [
                {"content": {"parts": [{"text": "{}"}]}}
            ],
            "usageMetadata": {},
        }

    monkeypatch.setattr(GoogleProvider, "_http_post", fake_post)
    provider = GoogleProvider(_model_config("google", "gemini-2.5-pro"))
    provider._send_request(LLMRequest(prompt="p"))
    assert "response_mime_type" not in captured["payload"]["generationConfig"]


def test_openai_provider_sets_response_format_when_json_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "{\"summary\":\"ok\",\"artifacts\":{}}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(OpenAIProvider, "_http_post", fake_post)
    provider = OpenAIProvider(_model_config("openai", "gpt-4o"))
    provider._send_request(LLMRequest(prompt="p", response_format="json"))
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_openai_provider_omits_response_format_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

    monkeypatch.setattr(OpenAIProvider, "_http_post", fake_post)
    provider = OpenAIProvider(_model_config("openai", "gpt-4o"))
    provider._send_request(LLMRequest(prompt="p"))
    assert "response_format" not in captured["payload"]


def test_anthropic_provider_prepends_strict_directive_when_json_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "content": [{"text": "{\"summary\":\"ok\",\"artifacts\":{}}"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(AnthropicProvider, "_http_post", fake_post)
    provider = AnthropicProvider(_model_config("anthropic", "claude-sonnet-4-5"))
    provider._send_request(
        LLMRequest(prompt="p", system="You are a helper.", response_format="json")
    )
    system_text = captured["payload"]["system"]
    # Directive comes first so the model sees the JSON requirement before
    # any caller-supplied framing.
    assert system_text.startswith("You MUST respond with a single raw JSON object")
    assert "You are a helper." in system_text


def test_anthropic_provider_leaves_system_unchanged_without_json_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "k")
    captured: dict[str, Any] = {}

    def fake_post(self, url, payload, headers):
        captured["payload"] = payload
        return {
            "content": [{"text": "ok"}],
            "usage": {},
        }

    monkeypatch.setattr(AnthropicProvider, "_http_post", fake_post)
    provider = AnthropicProvider(_model_config("anthropic", "claude-sonnet-4-5"))
    provider._send_request(LLMRequest(prompt="p", system="You are a helper."))
    assert captured["payload"]["system"] == "You are a helper."


# ---------------------------------------------------------------------------
# Worker integration — single retry on parse failure
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedRouter:
    """Router stand-in that returns queued responses."""

    responses: list[LLMResponse]
    calls: list[LLMRequest] = field(default_factory=list)

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if not self.responses:
            raise RuntimeError("Router exhausted — test script is short")
        return self.responses.pop(0)


def _build_fake_context() -> Any:
    """Build a minimal :class:`WorkerAdapterContext` using real builder
    types, matching the pattern from :mod:`tests.test_llm_worker_adapter`.

    Using real types (rather than SimpleNamespace) ensures the fallback
    path has every attribute the deterministic adapter reaches for —
    otherwise an unrelated ``KeyError`` masquerades as the bug we're
    trying to test."""
    from builder.events import EventBroker
    from builder.store import BuilderStore
    from builder.types import (
        BuilderProject,
        BuilderSession,
        BuilderTask,
        CoordinatorExecutionRun,
        SpecialistRole,
        WorkerExecutionState,
        WorkerExecutionStatus,
    )
    from builder.worker_adapters import WorkerAdapterContext

    events = EventBroker()
    store = BuilderStore(db_path=":memory:")
    project = BuilderProject(name="envelope-parser test")
    session = BuilderSession(project_id=project.project_id, title="t")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Build helper",
        description="a worker exercise",
    )
    state = WorkerExecutionState(
        node_id="plan:worker-1",
        worker_role=SpecialistRole.BUILD_ENGINEER,
        status=WorkerExecutionStatus.ACTING,
    )
    run = CoordinatorExecutionRun(
        plan_id="plan-1",
        root_task_id=task.task_id,
        session_id=session.session_id,
        project_id=project.project_id,
        goal="a worker exercise",
        worker_states=[state],
    )
    return WorkerAdapterContext(
        task=task,
        state=state,
        run=run,
        events=events,
        store=store,
        context={
            "expected_artifacts": [],
            "selected_tools": [],
            "skill_candidates": [],
            "dependency_summaries": {},
            "context_boundary": "test_boundary",
        },
        routed={
            "specialist": "build_engineer",
            "recommended_tools": [],
            "permission_scope": [],
            "provenance": {
                "routed_by": "test",
                "routing_reason": "test",
            },
        },
    )


def _fake_response(text: str) -> LLMResponse:
    return LLMResponse(
        provider="google",
        model="gemini-2.5-pro",
        text=text,
        prompt_tokens=5,
        completion_tokens=5,
        total_tokens=10,
        latency_ms=1.0,
        metadata={},
    )


def test_worker_retry_recovers_from_prose_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call returns prose preamble → parser still extracts JSON →
    no retry needed. Demonstrates the primary fix path."""
    good_payload = '{"summary": "done", "artifacts": {}}'
    router = _ScriptedRouter(
        responses=[_fake_response(f"Here you go:\n\n{good_payload}\n\nLet me know.")]
    )
    adapter = LLMWorkerAdapter(router=router)

    # Stub build_worker_prompt so we don't need the full coordinator wire-up.
    from builder import llm_worker

    def fake_prompt(**_kwargs):
        return types_ns(system="sys", user="usr")

    import types as _types
    types_ns = _types.SimpleNamespace
    monkeypatch.setattr(llm_worker, "build_worker_prompt", fake_prompt)

    result = adapter.execute(_build_fake_context())
    # One router call, parser accepted the payload, no fallback used.
    assert len(router.calls) == 1
    assert router.calls[0].response_format == "json"
    assert result.summary == "done"


def test_worker_retries_once_when_first_response_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call returns unparseable garbage → second call returns clean
    JSON → worker recovers without falling back."""
    router = _ScriptedRouter(
        responses=[
            _fake_response("I apologise — I cannot produce JSON today."),
            _fake_response('{"summary": "saved", "artifacts": {}}'),
        ]
    )
    adapter = LLMWorkerAdapter(router=router)

    from builder import llm_worker
    import types as _types

    monkeypatch.setattr(
        llm_worker,
        "build_worker_prompt",
        lambda **_k: _types.SimpleNamespace(system="sys", user="usr"),
    )

    result = adapter.execute(_build_fake_context())
    assert len(router.calls) == 2, "retry path should fire exactly once"
    # The retry request carries the strict suffix on the system prompt.
    assert "single raw JSON object" in (router.calls[1].system or "")
    # Retry metadata records why the retry happened.
    assert router.calls[1].metadata["retry_reason"] == "no_json_object"
    assert result.summary == "saved"


def test_worker_falls_back_after_retry_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both calls return garbage → worker falls back to the deterministic
    adapter (no infinite loop)."""
    router = _ScriptedRouter(
        responses=[
            _fake_response("still no JSON"),
            _fake_response("still no JSON, round two"),
        ]
    )
    adapter = LLMWorkerAdapter(router=router)

    from builder import llm_worker
    import types as _types

    monkeypatch.setattr(
        llm_worker,
        "build_worker_prompt",
        lambda **_k: _types.SimpleNamespace(system="sys", user="usr"),
    )

    result = adapter.execute(_build_fake_context())
    assert len(router.calls) == 2
    # Fallback adapter was used — check via the output_payload adapter tag.
    adapter_tag = result.output_payload.get("adapter")
    assert adapter_tag != LLMWorkerAdapter.name


def test_worker_does_not_retry_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-level exception goes straight to fallback — retrying
    would just double the cost of a real outage."""

    class _AlwaysFail:
        calls: list[LLMRequest] = []

        def generate(self, request: LLMRequest) -> LLMResponse:
            self.calls.append(request)
            raise RuntimeError("upstream down")

    router = _AlwaysFail()
    adapter = LLMWorkerAdapter(router=router)

    from builder import llm_worker
    import types as _types

    monkeypatch.setattr(
        llm_worker,
        "build_worker_prompt",
        lambda **_k: _types.SimpleNamespace(system="sys", user="usr"),
    )

    adapter.execute(_build_fake_context())
    assert len(router.calls) == 1  # exactly one attempt, then fallback
