"""LLM-backed worker adapter for the coordinator-worker runtime.

This is the F2 execution substrate: instead of returning a deterministic,
role-aware stub, :class:`LLMWorkerAdapter` calls a provider through
:class:`optimizer.providers.LLMRouter`, parses a JSON envelope out of the
response, and hands the coordinator a real :class:`WorkerExecutionResult`.

Operational guarantees:

- Parse / provider failures fall back to the deterministic adapter so a
  broken model or quota trip never aborts the run mid-turn.
- Every adapter run emits a single ``WORKER_MESSAGE_DELTA`` event with the
  raw response text so the REPL can render live worker commentary.
- Expected artifacts declared in the coordinator plan are honored: the LLM
  is required to return them, and missing keys trip the fallback path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from builder.events import BuilderEventType
from builder.types import (
    SpecialistRole,
    WorkerExecutionResult,
)
from builder.worker_adapters import (
    DeterministicWorkerAdapter,
    WorkerAdapter,
    WorkerAdapterContext,
)
from builder.worker_prompts import build_worker_prompt
from optimizer.providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


class LLMWorkerAdapter:
    """Worker adapter that drives a real provider through :class:`LLMRouter`."""

    name = "llm_worker_adapter"

    def __init__(
        self,
        router: LLMRouter,
        *,
        fallback: WorkerAdapter | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> None:
        self._router = router
        self._fallback = fallback or DeterministicWorkerAdapter()
        self._temperature = temperature
        self._max_tokens = max_tokens

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run the LLM worker, returning parsed artifacts or fallback output."""
        prompt = build_worker_prompt(
            state=context.state,
            context=context.context,
            routed=context.routed,
        )
        request = LLMRequest(
            prompt=prompt.user,
            system=prompt.system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata={
                "worker_role": context.state.worker_role.value,
                "plan_id": context.run.plan_id,
                "run_id": context.run.run_id,
                "node_id": context.state.node_id,
            },
            # Ask the provider for JSON-only output so Gemini's
            # response_mime_type, OpenAI's response_format, and the
            # Anthropic directive all kick in. The envelope parser is a
            # belt-and-braces backstop when the provider still slips up.
            response_format="json",
        )

        response, parse_error = self._call_and_parse(context, request)
        if parse_error == _PROVIDER_ERROR_KIND:
            # Network / auth failure — retrying would just double the
            # outage cost. Straight to fallback.
            return self._fallback.execute(context)
        if parse_error is not None:
            # Provider returned *something* but it didn't parse. One
            # retry with a stricter suffix often recovers; cap at one.
            retry_request = _with_strict_suffix(request, parse_error)
            response, parse_error = self._call_and_parse(
                context,
                retry_request,
                is_retry=True,
            )
            if parse_error is not None or response is None:
                return self._fallback.execute(context)

        assert response is not None  # for type-checkers; parse_error is None here
        parsed_envelope, raw_response = response

        expected = list(context.context.get("expected_artifacts", []))
        artifacts = parsed_envelope.get("artifacts") or {}
        if expected and not all(name in artifacts for name in expected):
            logger.warning(
                "llm_worker: response missing expected artifacts — falling back",
                extra={
                    "worker_role": context.state.worker_role.value,
                    "expected": expected,
                    "received": sorted(artifacts.keys()),
                },
            )
            return self._fallback.execute(context)

        return _to_execution_result(
            context=context,
            parsed=parsed_envelope,
            provider=raw_response.provider,
            model=raw_response.model,
            total_tokens=raw_response.total_tokens,
        )

    def _call_and_parse(
        self,
        context: WorkerAdapterContext,
        request: LLMRequest,
        *,
        is_retry: bool = False,
    ) -> tuple[
        tuple[dict[str, Any], Any] | None,
        str | None,
    ]:
        """Invoke the router and parse the envelope, returning
        ``((envelope, response), None)`` on success or ``(None, failure_kind)``
        on provider/parse failure.

        Splitting this helper out of :meth:`execute` lets the retry path
        reuse the same logging + delta-emission behaviour without a
        second copy of the error handling."""
        try:
            response = self._router.generate(request)
        except Exception as exc:
            logger.warning(
                "llm_worker: provider call failed — falling back to deterministic",
                extra={
                    "worker_role": context.state.worker_role.value,
                    "error": str(exc),
                    "is_retry": is_retry,
                },
            )
            return None, _PROVIDER_ERROR_KIND

        self._emit_message_delta(context, response.text)

        envelope, failure_kind = _parse_envelope(response.text)
        if envelope is None:
            logger.warning(
                "llm_worker: response was not valid JSON envelope — falling back",
                extra={
                    "worker_role": context.state.worker_role.value,
                    "failure_kind": failure_kind,
                    "is_retry": is_retry,
                    "raw_preview": (response.text or "")[:400],
                },
            )
            return None, failure_kind or "unknown"
        return (envelope, response), None

    def _emit_message_delta(
        self,
        context: WorkerAdapterContext,
        text: str,
    ) -> None:
        """Publish the raw LLM response as a WORKER_MESSAGE_DELTA event."""
        try:
            context.events.publish(
                BuilderEventType.WORKER_MESSAGE_DELTA,
                context.run.session_id,
                context.run.root_task_id,
                {
                    "run_id": context.run.run_id,
                    "node_id": context.state.node_id,
                    "worker_role": context.state.worker_role.value,
                    "project_id": context.run.project_id,
                    "text": text,
                },
            )
        except Exception:  # pragma: no cover - event bus must not break execution
            pass


_PROVIDER_ERROR_KIND = "provider_error"
"""Sentinel failure-kind for provider-side (network / auth / rate) errors.

Distinct from the parse-failure kinds so :meth:`LLMWorkerAdapter.execute`
can skip the retry path when the model never even spoke."""


_STRICT_RETRY_SYSTEM_SUFFIX = (
    "\n\nYour previous response did not parse as JSON. Reply with ONLY a "
    "single raw JSON object matching the schema described above. Do not "
    "wrap it in markdown code fences. Do not include any prose before or "
    "after the JSON."
)


def _with_strict_suffix(request: LLMRequest, failure_kind: str) -> LLMRequest:
    """Return a clone of ``request`` with a strict-JSON retry suffix on the
    system prompt. ``failure_kind`` is threaded into metadata so provider
    logs / cost telemetry can distinguish retries from fresh calls."""
    new_system = (request.system or "") + _STRICT_RETRY_SYSTEM_SUFFIX
    new_metadata = dict(request.metadata)
    new_metadata["retry_reason"] = failure_kind
    return LLMRequest(
        prompt=request.prompt,
        system=new_system,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        metadata=new_metadata,
        response_format=request.response_format,
    )


PARSE_FAILURE_NO_JSON_OBJECT = "no_json_object"
PARSE_FAILURE_DECODE_ERROR = "json_decode_error"
PARSE_FAILURE_NOT_MAPPING = "not_mapping"
PARSE_FAILURE_MISSING_KEYS = "missing_required_keys"
"""Failure-kind tags surfaced on the fallback log line and on the
diagnostic event so operators can tell 'the model wrote prose' apart
from 'the model emitted JSON but missed a key'."""

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(?P<body>.*?)\n?```\s*$",
    re.DOTALL,
)


def _parse_envelope(
    text: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the JSON envelope emitted by the LLM.

    Returns ``(envelope, None)`` on success and ``(None, failure_kind)``
    on failure. Failure kinds are the ``PARSE_FAILURE_*`` constants above
    so the caller can surface a specific diagnostic rather than one
    generic "invalid" message.

    The parser tolerates three real-world LLM shapes:

    1. Bare JSON object (the happy path).
    2. Markdown-fenced JSON — with or without a ``json`` language tag.
    3. JSON embedded in prose — "Sure! Here is the envelope: {…}" or a
       trailing "Let me know if…" tail. A balanced-brace scan extracts
       the first complete object; everything else is ignored.

    A single trailing-comma retry handles the other common Gemini
    slip-up so we don't spend a retry budget on a one-character typo."""
    if not text:
        return None, PARSE_FAILURE_NO_JSON_OBJECT

    candidate = _extract_json_candidate(text)
    if candidate is None:
        return None, PARSE_FAILURE_NO_JSON_OBJECT

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Retry once after stripping trailing commas — an LLM favourite
        # that's syntactically invalid but semantically obvious.
        relaxed = _strip_trailing_commas(candidate)
        if relaxed == candidate:
            return None, PARSE_FAILURE_DECODE_ERROR
        try:
            parsed = json.loads(relaxed)
        except json.JSONDecodeError:
            return None, PARSE_FAILURE_DECODE_ERROR

    if not isinstance(parsed, dict):
        return None, PARSE_FAILURE_NOT_MAPPING
    if "summary" not in parsed or "artifacts" not in parsed:
        return None, PARSE_FAILURE_MISSING_KEYS
    return parsed, None


def _extract_json_candidate(text: str) -> str | None:
    """Return the substring most likely to be the JSON envelope.

    Tries fenced-code extraction first, then falls through to a
    balanced-brace scan starting at the first ``{`` — which handles
    preamble / trailing prose. Returns ``None`` when no candidate
    object is found; the caller maps that to
    :data:`PARSE_FAILURE_NO_JSON_OBJECT`."""
    stripped = text.strip()
    fenced = _FENCE_RE.match(stripped)
    if fenced is not None:
        return fenced.group("body").strip()

    start = stripped.find("{")
    if start == -1:
        return None

    # Balanced-brace scan with string/escape awareness so a ``{`` inside
    # a string payload doesn't confuse the depth counter.
    depth = 0
    in_string = False
    escape_next = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return None


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_trailing_commas(text: str) -> str:
    """Remove the trailing commas some models emit before ``}`` / ``]``.

    Not a full relaxer — we keep JSON strict in every other respect so a
    genuinely malformed payload still fails loudly."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _to_execution_result(
    *,
    context: WorkerAdapterContext,
    parsed: dict[str, Any],
    provider: str,
    model: str,
    total_tokens: int,
) -> WorkerExecutionResult:
    """Convert a validated JSON envelope into a :class:`WorkerExecutionResult`."""
    state = context.state
    output_payload = dict(parsed.get("output_payload") or {})
    output_payload.setdefault("adapter", LLMWorkerAdapter.name)
    output_payload.setdefault(
        "specialist", context.routed.get("specialist", state.worker_role.value)
    )
    output_payload.setdefault(
        "recommended_tools", list(context.routed.get("recommended_tools", []))
    )
    output_payload.setdefault(
        "permission_scope", list(context.routed.get("permission_scope", []))
    )
    output_payload.setdefault("review_required", _default_review_required(state.worker_role))

    return WorkerExecutionResult(
        node_id=state.node_id,
        worker_role=state.worker_role,
        summary=str(parsed.get("summary") or "").strip(),
        artifacts=dict(parsed.get("artifacts") or {}),
        context_used={
            "context_boundary": context.context.get("context_boundary"),
            "selected_tools": list(context.context.get("selected_tools", [])),
            "skill_candidates": list(context.context.get("skill_candidates", [])),
            "dependency_summaries": dict(context.context.get("dependency_summaries", {})),
        },
        output_payload=output_payload,
        provenance={
            "run_id": context.run.run_id,
            "plan_id": context.run.plan_id,
            "node_id": state.node_id,
            "routed_by": context.routed.get("provenance", {}).get("routed_by"),
            "routing_reason": context.routed.get("provenance", {}).get("routing_reason"),
            "adapter": LLMWorkerAdapter.name,
            "provider": provider,
            "model": model,
            "total_tokens": total_tokens,
        },
    )


_REVIEW_REQUIRED_DEFAULTS = {
    SpecialistRole.BUILD_ENGINEER: True,
    SpecialistRole.TOOL_ENGINEER: True,
    SpecialistRole.SKILL_AUTHOR: True,
    SpecialistRole.GUARDRAIL_AUTHOR: True,
    SpecialistRole.OPTIMIZATION_ENGINEER: True,
    SpecialistRole.DEPLOYMENT_ENGINEER: True,
    SpecialistRole.RELEASE_MANAGER: True,
}


def _default_review_required(role: SpecialistRole) -> bool:
    """Roles that touch source, policy, or deploy default to review-required."""
    return _REVIEW_REQUIRED_DEFAULTS.get(role, False)


__all__ = [
    "LLMWorkerAdapter",
]
