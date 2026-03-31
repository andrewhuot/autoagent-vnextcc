"""Helpers for describing how an eval actually executed."""

from __future__ import annotations

from typing import Any, Literal


EvalExecutionMode = Literal["mock", "live", "mixed"]

_VALID_EVAL_MODES = {"mock", "live", "mixed"}


def requested_live_mode(
    runtime: Any,
    *,
    force_live: bool = False,
    require_live: bool = False,
) -> bool:
    """Return whether the caller intends to execute on live providers.

    WHY: The runtime config may prefer mock mode, but CLI flags like
    ``--real-agent`` and ``--require-live`` should override that default.
    """
    if force_live or require_live:
        return True
    optimizer = getattr(runtime, "optimizer", None)
    return not bool(getattr(optimizer, "use_mock", False))


def resolve_eval_execution_mode(
    *,
    requested_live: bool,
    eval_agent: Any | None,
) -> EvalExecutionMode:
    """Return the effective eval mode for one completed run.

    ``mock`` means the run was intentionally simulated from the start.
    ``live`` means the run stayed on live providers end-to-end.
    ``mixed`` means the caller intended live execution but the run ended up
    using mock behavior for some or all of the cases.
    """
    if not requested_live:
        return "mock"
    if eval_agent is None:
        return "mixed"
    return "mixed" if bool(getattr(eval_agent, "mock_mode", False)) else "live"


def parse_eval_execution_mode(value: Any) -> EvalExecutionMode | None:
    """Normalize a serialized eval mode field when present."""
    normalized = str(value or "").strip().lower()
    if normalized in _VALID_EVAL_MODES:
        return normalized  # type: ignore[return-value]
    return None


def infer_eval_execution_mode(payload: dict[str, Any]) -> EvalExecutionMode | None:
    """Infer eval mode from a serialized payload, including legacy runs.

    WHY: Older eval snapshots predate the explicit ``mode`` field. We infer the
    most likely value from recorded warnings so status/show surfaces stay
    graceful while newer runs write the canonical field directly.
    """
    explicit = parse_eval_execution_mode(payload.get("mode"))
    if explicit is not None:
        return explicit

    scores = payload.get("scores")
    warnings: list[str] = []
    if isinstance(scores, dict):
        raw_warnings = scores.get("warnings")
        if isinstance(raw_warnings, list):
            warnings.extend(str(item) for item in raw_warnings)
    raw_top_level_warnings = payload.get("warnings")
    if isinstance(raw_top_level_warnings, list):
        warnings.extend(str(item) for item in raw_top_level_warnings)

    warning_text = " ".join(warnings).lower()
    if "falling back" in warning_text or "fallback to mock" in warning_text:
        return "mixed"
    if "mock mode" in warning_text or "simulated" in warning_text or "mock_agent_response" in warning_text:
        return "mock"
    return None


def eval_mode_banner_label(mode: EvalExecutionMode | None) -> str:
    """Return the human-facing heading label for one eval mode."""
    if mode == "live":
        return "LIVE"
    if mode == "mixed":
        return "MIXED MODE - live fallback to mock"
    if mode == "mock":
        return "MOCK MODE - simulated"
    return "MODE UNKNOWN"


def eval_mode_status_label(mode: EvalExecutionMode | None) -> str:
    """Return a compact status label for tables and status surfaces."""
    if mode is None:
        return "N/A"
    return mode.upper()
